"""AST-level optimization passes.

Every pass works on a copy of the parsed source tree; nothing here ever
writes to disk. Line numbers are kept, so tracebacks still point at the
right lines of the original file.

Level 1 (default) passes are meant to be semantics-preserving:

* ``ConstantPropagation`` - module-level ``UPPER_CASE = <literal>`` names
  that are never rebound are substituted at their later uses.
* ``ConstantFolding``     - ``2 * 60 * 60``, ``"a" + "b"``, ``not True``,
  ``3 < 4``, ``len("abc")``, ``x if True else y`` ... are computed once.
* ``DeadCodeElimination`` - ``if False:`` / ``while 0:`` branches and
  statements after ``return`` / ``raise`` / ``break`` / ``continue`` go away.

Level 2 passes trade a little strictness for speed (see README):

* ``MethodHoisting``      - ``out.append(x)`` inside a loop becomes a call to
  a bound method looked up once before the loop.
* ``StrengthReduction``   - ``x ** 2`` becomes ``x * x`` for plain names.
"""

from __future__ import annotations

import ast
import builtins
import copy
import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_SIMPLE_CONST = (int, float, complex, bool, str, bytes, type(None))
_MAX_SEQ = 256          # longest str/bytes/tuple we are willing to inline
_MAX_INT_BITS = 1024    # largest int we are willing to inline

# Builtins that are pure functions of their (constant) arguments.
_PURE_BUILTINS = {
    "abs", "bool", "bytes", "chr", "complex", "divmod", "float", "hex",
    "int", "len", "max", "min", "oct", "ord", "pow", "repr", "round",
    "str", "sum", "tuple", "bin", "ascii", "hash",
}
_PURE_BUILTINS.discard("hash")  # str hashes are randomised per process

# Names whose presence means the program may poke at namespaces
# dynamically, which makes name-based reasoning unsafe.
_DYNAMIC_NAMES = {"globals", "locals", "vars", "exec", "eval", "__builtins__",
                  "builtins", "setattr", "delattr", "__dict__", "sys"}


def _is_small_const(value) -> bool:
    if isinstance(value, bool) or value is None:
        return True
    if isinstance(value, int):
        return value.bit_length() <= _MAX_INT_BITS
    if isinstance(value, float):
        return not (math.isnan(value))  # NaN != NaN; keep it out of folding
    if isinstance(value, complex):
        return True
    if isinstance(value, (str, bytes)):
        return len(value) <= _MAX_SEQ
    if isinstance(value, tuple):
        return len(value) <= _MAX_SEQ and all(_is_small_const(v) for v in value)
    if isinstance(value, frozenset):
        return len(value) <= _MAX_SEQ and all(_is_small_const(v) for v in value)
    return False


def _const_value(node):
    """Return (True, value) if *node* is a literal constant expression."""
    if isinstance(node, ast.Constant):
        return True, node.value
    if isinstance(node, ast.Tuple) and isinstance(node.ctx, ast.Load):
        vals = []
        for elt in node.elts:
            ok, v = _const_value(elt)
            if not ok:
                return False, None
            vals.append(v)
        return True, tuple(vals)
    return False, None


def _make_const(value, like: ast.AST) -> ast.expr:
    if isinstance(value, tuple):
        node = ast.Tuple(elts=[_make_const(v, like) for v in value], ctx=ast.Load())
    else:
        node = ast.Constant(value=value)
    return ast.copy_location(node, like)


def _bound_names(node: ast.AST) -> set[str]:
    """Every name that *node* (or anything inside it) binds or deletes."""
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
            names.add(sub.id)
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(sub.name)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            for alias in sub.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(sub, ast.arg):
            names.add(sub.arg)
        elif isinstance(sub, (ast.Global, ast.Nonlocal)):
            names.update(sub.names)
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            names.add(sub.name)
        elif isinstance(sub, (ast.MatchAs, ast.MatchStar)) and sub.name:
            names.add(sub.name)
        elif isinstance(sub, ast.MatchMapping) and sub.rest:
            names.add(sub.rest)
    return names


def _all_name_ids(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)
    }


def _has_star_import(tree: ast.AST) -> bool:
    return any(
        isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)
        for n in ast.walk(tree)
    )


@dataclass
class Report:
    """What the optimizer changed, for ``OPTICOMP_VERBOSE`` / ``--report``."""

    changes: dict[str, int] = field(default_factory=dict)

    def bump(self, what: str, n: int = 1) -> None:
        self.changes[what] = self.changes.get(what, 0) + n

    def __bool__(self) -> bool:
        return bool(self.changes)

    def summary(self) -> str:
        if not self.changes:
            return "no changes"
        return ", ".join(f"{k}: {v}" for k, v in sorted(self.changes.items()))


# ---------------------------------------------------------------------------
# Level 1 passes
# ---------------------------------------------------------------------------

class ConstantPropagation(ast.NodeTransformer):
    """Inline module-level ``UPPER_CASE = <literal>`` constants.

    Only names that are assigned exactly once, at module top level, never
    rebound anywhere else in the file (no function argument, local, global
    statement, import, del ...) are touched, and only at uses that appear
    after the assignment. The assignment itself is kept, so the module still
    has the attribute.
    """

    def __init__(self, tree: ast.Module, report: Report):
        self.report = report
        self.consts: dict[str, tuple[int, object]] = {}
        if _has_star_import(tree) or (_all_name_ids(tree) & _DYNAMIC_NAMES):
            return

        assign_count: dict[str, int] = {}
        for sub in ast.walk(tree):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
                assign_count[sub.id] = assign_count.get(sub.id, 0) + 1
        other_bindings = set()
        for sub in ast.walk(tree):
            if not (isinstance(sub, ast.Name)):
                other_bindings |= _bound_names_shallow(sub)

        for stmt in tree.body:
            target = value = None
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                target, value = stmt.targets[0], stmt.value
            elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None and stmt.simple:
                target, value = stmt.target, stmt.value
            if not isinstance(target, ast.Name):
                continue
            name = target.id
            if not (name.isupper() and name.isidentifier()):
                continue
            if assign_count.get(name) != 1 or name in other_bindings:
                continue
            ok, v = _const_value(value)
            if ok and _is_small_const(v):
                self.consts[name] = (stmt.end_lineno or stmt.lineno, v)

    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load) and node.id in self.consts:
            line, value = self.consts[node.id]
            if node.lineno > line:
                self.report.bump("constants propagated")
                return _make_const(value, node)
        return node


def _bound_names_shallow(node: ast.AST) -> set[str]:
    """Names bound by *node* itself (not its children)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {(a.asname or a.name).split(".")[0] for a in node.names}
    if isinstance(node, ast.arg):
        return {node.arg}
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return set(node.names)
    if isinstance(node, ast.ExceptHandler) and node.name:
        return {node.name}
    if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
        return {node.name}
    if isinstance(node, ast.MatchMapping) and node.rest:
        return {node.rest}
    return set()


_BINOPS = {
    ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b, ast.LShift: lambda a, b: a << b,
    ast.RShift: lambda a, b: a >> b, ast.BitOr: lambda a, b: a | b,
    ast.BitXor: lambda a, b: a ^ b, ast.BitAnd: lambda a, b: a & b,
}
_UNARYOPS = {
    ast.UAdd: lambda a: +a, ast.USub: lambda a: -a,
    ast.Not: lambda a: not a, ast.Invert: lambda a: ~a,
}
_CMPOPS = {
    ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
}


class ConstantFolding(ast.NodeTransformer):
    """Evaluate expressions whose operands are all literals."""

    def __init__(self, tree: ast.Module, report: Report):
        self.report = report
        if _has_star_import(tree) or (_all_name_ids(tree) & _DYNAMIC_NAMES):
            self.pure_builtins: set[str] = set()
        else:
            self.pure_builtins = _PURE_BUILTINS - _bound_names(tree)

    def _fold(self, node, fn, *values):
        # Guard against expressions that would blow up in size or time.
        if isinstance(node, ast.BinOp):
            a, b = values
            if isinstance(node.op, ast.Pow) and isinstance(a, int) and isinstance(b, int):
                if b < 0 or b > 256 or a.bit_length() * b > _MAX_INT_BITS:
                    return node
            if isinstance(node.op, ast.LShift) and isinstance(b, int) and b > _MAX_INT_BITS:
                return node
            if isinstance(node.op, ast.Mult) and any(
                isinstance(x, (str, bytes, tuple)) for x in (a, b)
            ):
                other = b if isinstance(a, (str, bytes, tuple)) else a
                seq = a if isinstance(a, (str, bytes, tuple)) else b
                if not isinstance(other, int) or len(seq) * max(other, 0) > _MAX_SEQ:
                    return node
        try:
            result = fn(*values)
        except Exception:  # e.g. 1/0 - leave it so it fails at runtime as before
            return node
        if not _is_small_const(result) or isinstance(result, frozenset):
            return node
        self.report.bump("expressions folded")
        return _make_const(result, node)

    def visit_BinOp(self, node):
        self.generic_visit(node)
        ok_l, a = _const_value(node.left)
        ok_r, b = _const_value(node.right)
        if ok_l and ok_r and type(node.op) in _BINOPS:
            return self._fold(node, _BINOPS[type(node.op)], a, b)
        return node

    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        ok, a = _const_value(node.operand)
        if ok:
            return self._fold(node, _UNARYOPS[type(node.op)], a)
        return node

    def visit_Compare(self, node):
        self.generic_visit(node)
        values = []
        for operand in [node.left, *node.comparators]:
            ok, v = _const_value(operand)
            if not ok:
                return node
            values.append(v)
        ops = [_CMPOPS.get(type(op)) for op in node.ops]
        if None in ops:  # `is` / `is not` on literals: identity is not ours to decide
            return node

        def chain():
            return all(op(values[i], values[i + 1]) for i, op in enumerate(ops))

        return self._fold(node, chain)

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        values = list(node.values)
        is_and = isinstance(node.op, ast.And)
        while len(values) > 1:
            ok, v = _const_value(values[0])
            if not ok:
                break
            # `C and x` -> x if C truthy else C ; `C or x` -> C if truthy else x
            if bool(v) == is_and:
                values.pop(0)
                self.report.bump("expressions folded")
            else:
                self.report.bump("expressions folded")
                return values[0]
        if len(values) == 1:
            return values[0]
        node.values = values
        return node

    def visit_IfExp(self, node):
        self.generic_visit(node)
        ok, v = _const_value(node.test)
        if ok:
            self.report.bump("expressions folded")
            return node.body if v else node.orelse
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in self.pure_builtins
            and not node.keywords
        ):
            args = []
            for a in node.args:
                ok, v = _const_value(a)
                if not ok:
                    return node
                args.append(v)
            fn = getattr(builtins, node.func.id)
            return self._fold(node, lambda: fn(*args))
        return node


class DeadCodeElimination(ast.NodeTransformer):
    """Drop branches that can never run and code after unconditional exits."""

    def __init__(self, tree: ast.Module, report: Report):
        self.report = report
        self.function_depth = 0

    # --- safety -----------------------------------------------------------
    def _can_drop(self, stmts: list[ast.stmt]) -> bool:
        for stmt in stmts:
            for sub in ast.walk(stmt):
                # Removing a yield would turn a generator into a function;
                # removing global/nonlocal would change scoping.
                if isinstance(sub, (ast.Yield, ast.YieldFrom, ast.Await,
                                    ast.Global, ast.Nonlocal)):
                    return False
                if isinstance(sub, ast.Name) and sub.id in ("super", "__class__"):
                    return False
            # Inside a function, removing an assignment can turn a local
            # into a global lookup (UnboundLocalError -> different result).
            if self.function_depth and _bound_names(stmt):
                return False
        return True

    # --- statement lists ----------------------------------------------------
    def _visit_block(self, stmts: list[ast.stmt]) -> list[ast.stmt]:
        out: list[ast.stmt] = []
        for i, stmt in enumerate(stmts):
            new = self.visit(stmt)
            if new is None:
                continue
            new_list = new if isinstance(new, list) else [new]
            out.extend(new_list)
            if new_list and isinstance(new_list[-1], (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                rest = stmts[i + 1:]
                if rest and self._can_drop(rest):
                    self.report.bump("unreachable statements removed", len(rest))
                    break
        return out

    def generic_visit(self, node):
        for name, value in ast.iter_fields(node):
            if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                setattr(node, name, self._visit_block(value))
            elif isinstance(value, list):
                setattr(node, name, [self.visit(v) if isinstance(v, ast.AST) else v for v in value])
            elif isinstance(value, ast.AST):
                setattr(node, name, self.visit(value))
        return node

    def _visit_scope(self, node):
        self.function_depth += 1
        try:
            self.generic_visit(node)
        finally:
            self.function_depth -= 1
        if not node.body:
            node.body = [ast.copy_location(ast.Pass(), node)]
        return node

    visit_FunctionDef = visit_AsyncFunctionDef = visit_Lambda = _visit_scope

    def visit_If(self, node: ast.If):
        self.generic_visit(node)
        ok, v = _const_value(node.test)
        if not ok:
            return node
        keep, drop = (node.body, node.orelse) if v else (node.orelse, node.body)
        if not self._can_drop(drop):
            return node
        self.report.bump("dead branches removed")
        return keep or None

    def visit_While(self, node: ast.While):
        self.generic_visit(node)
        ok, v = _const_value(node.test)
        if ok and not v and self._can_drop(node.body):
            self.report.bump("dead branches removed")
            return node.orelse or None
        return node

    def visit_Module(self, node):
        self.generic_visit(node)
        return node


def _fix_empty_blocks(tree: ast.AST) -> None:
    """Any compound statement whose body became empty gets a ``pass``."""
    for node in ast.walk(tree):
        for name in ("body", "orelse", "finalbody"):
            block = getattr(node, name, None)
            if (
                name == "body"
                and isinstance(block, list)
                and not block
                and not isinstance(node, ast.Module)
            ):
                node.body = [ast.copy_location(ast.Pass(), node)]
        if isinstance(node, ast.Try) and not node.handlers and not node.finalbody:
            node.finalbody = [ast.copy_location(ast.Pass(), node)]


# ---------------------------------------------------------------------------
# Level 2 passes
# ---------------------------------------------------------------------------

_HOISTABLE_METHODS = {
    "append", "extend", "add", "appendleft", "update", "discard",
    "write", "put", "insert", "setdefault", "get",
}


class MethodHoisting(ast.NodeTransformer):
    """Look up ``obj.method`` once before a loop instead of every iteration.

    Applied only inside functions, only to local variables that the loop
    never rebinds (or assigns attributes on), only to a fixed list of common
    container methods, and only to calls that run unconditionally at the top
    level of the loop body. The assumption it adds: the object already exists
    when the loop starts, even if the loop would run zero times.
    """

    def __init__(self, tree: ast.Module, report: Report):
        self.report = report
        self.counter = 0
        self.locals_stack: list[set[str]] = []

    def visit_FunctionDef(self, node):
        func_locals = _bound_names(ast.Module(body=node.body, type_ignores=[])) | {
            a.arg for a in ast.walk(node.args) if isinstance(a, ast.arg)
        }
        declared = {
            n for sub in ast.walk(node) if isinstance(sub, (ast.Global, ast.Nonlocal))
            for n in sub.names
        }
        self.locals_stack.append(func_locals - declared)
        self.generic_visit(node)
        node.body = self._process_block(node.body)
        self.locals_stack.pop()
        return node

    visit_AsyncFunctionDef = visit_FunctionDef

    def _process_block(self, stmts):
        out = []
        for stmt in stmts:
            if isinstance(stmt, (ast.For, ast.While)):
                out.extend(self._hoist(stmt))
            else:
                out.append(stmt)
            # recurse into nested blocks of compound statements
            for name in ("body", "orelse", "finalbody"):
                block = getattr(stmt, name, None)
                if isinstance(block, list) and block and isinstance(block[0], ast.stmt) \
                        and not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    setattr(stmt, name, self._process_block(block))
            for handler in getattr(stmt, "handlers", []) or []:
                handler.body = self._process_block(handler.body)
        return out

    def _hoist(self, loop):
        if not self.locals_stack:
            return [loop]
        local_names = self.locals_stack[-1]
        rebound = _bound_names(loop)
        attr_stores = {
            n.value.id for n in ast.walk(loop)
            if isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del))
            and isinstance(n.value, ast.Name)
        }
        hoisted: dict[tuple[str, str], str] = {}
        pre: list[ast.stmt] = []

        for stmt in loop.body:
            call_nodes = []
            if isinstance(stmt, ast.Expr):
                call_nodes.append(stmt.value)
            elif isinstance(stmt, (ast.Assign, ast.AugAssign, ast.AnnAssign)) and stmt.value:
                call_nodes.append(stmt.value)
            for call in call_nodes:
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.attr in _HOISTABLE_METHODS
                ):
                    continue
                obj, attr = call.func.value.id, call.func.attr
                if obj not in local_names or obj in rebound or obj in attr_stores:
                    continue
                key = (obj, attr)
                if key not in hoisted:
                    alias = f"_oc_{obj}_{attr}_{self.counter}"
                    self.counter += 1
                    hoisted[key] = alias
                    pre.append(ast.copy_location(
                        ast.Assign(
                            targets=[ast.Name(id=alias, ctx=ast.Store())],
                            value=ast.Attribute(value=ast.Name(id=obj, ctx=ast.Load()),
                                                attr=attr, ctx=ast.Load()),
                        ),
                        loop,
                    ))
                # Rewrite every matching call in the loop (not only this one).
        if not hoisted:
            return [loop]

        class _Rewrite(ast.NodeTransformer):
            def visit_Call(inner, call):
                inner.generic_visit(call)
                f = call.func
                if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                    alias = hoisted.get((f.value.id, f.attr))
                    if alias:
                        call.func = ast.copy_location(ast.Name(id=alias, ctx=ast.Load()), f)
                return call

            # Don't reach into nested scopes - the alias isn't visible there
            # in the same way and the object may differ.
            def visit_FunctionDef(inner, n):
                return n

            visit_AsyncFunctionDef = visit_Lambda = visit_ClassDef = visit_FunctionDef

        loop.body = [_Rewrite().visit(s) for s in loop.body]
        self.report.bump("loop methods hoisted", len(hoisted))
        return pre + [loop]


class StrengthReduction(ast.NodeTransformer):
    """``x ** 2`` -> ``x * x`` when ``x`` is a plain name."""

    def __init__(self, tree: ast.Module, report: Report):
        self.report = report

    def visit_BinOp(self, node):
        self.generic_visit(node)
        if (
            isinstance(node.op, ast.Pow)
            and isinstance(node.left, ast.Name)
            and isinstance(node.right, ast.Constant)
            and type(node.right.value) is int
            and node.right.value == 2
        ):
            self.report.bump("powers reduced")
            return ast.copy_location(
                ast.BinOp(left=node.left, op=ast.Mult(),
                          right=ast.Name(id=node.left.id, ctx=ast.Load())),
                node,
            )
        return node


LEVEL_1 = (ConstantPropagation, ConstantFolding, DeadCodeElimination)
LEVEL_2 = (StrengthReduction, MethodHoisting)


def optimize_tree(tree: ast.Module, level: int = 1) -> tuple[ast.Module, Report]:
    """Return an optimized *copy* of ``tree`` and a report of what changed."""
    tree = copy.deepcopy(tree)
    report = Report()
    passes = list(LEVEL_1) + (list(LEVEL_2) if level >= 2 else [])
    if level <= 0:
        passes = []
    # Folding can expose new dead code and vice versa; two rounds is plenty.
    for round_no in range(2):
        for cls in passes:
            if cls in LEVEL_2 and round_no > 0:
                continue  # level-2 passes only need (and should get) one run
            tree = cls(tree, report).visit(tree)
            _fix_empty_blocks(tree)
    ast.fix_missing_locations(tree)
    return tree, report


def optimize_source(source: str, filename: str = "<string>", level: int = 1):
    """Parse ``source`` and return ``(optimized_tree, report)``."""
    tree = ast.parse(source, filename=filename)
    return optimize_tree(tree, level)
