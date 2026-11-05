"""Scope resolution and a small, conservative type inference.

``Analysis(tree)`` answers two questions for the passes:

* ``resolve(name_node)`` - does this ``Name`` refer to a builtin, to a
  variable (and which one), or to something we can't reason about?
* ``type_of(expr)`` - is this expression *guaranteed* to evaluate to an
  exact ``int`` / ``float`` / ``str`` / ``bool`` / ``list`` / ``dict`` /
  ``set`` / ``tuple`` (not a subclass)? ``None`` means "don't know".

A variable gets a type only when *every* binding of it in the file produces
that type. Anything else that binds it (an argument, tuple unpacking,
``with ... as``, ``import``, ``del``, a for-loop over something other than
``range`` ...) makes it unknown. If the file uses ``exec``, ``eval``,
``globals()``, ``locals()``, ``vars()``, ``import *`` and similar, nothing is
resolved at all.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

DYNAMIC_NAMES = {"globals", "locals", "vars", "exec", "eval", "__builtins__",
                 "builtins", "__main__", "__import__", "importlib"}

INT, FLOAT, STR, BOOL, LIST, DICT, SET, TUPLE = (
    "int", "float", "str", "bool", "list", "dict", "set", "tuple")
_TOP = "?"  # "no information yet" during the fixpoint

_COMPS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


class Scope:
    def __init__(self, node, kind, parent):
        self.node, self.kind, self.parent = node, kind, parent
        self.raw: dict[str, list[Binding]] = {}
        self.globals: set[str] = set()
        self.nonlocals: set[str] = set()
        self.locals: set[str] = set()

    def __repr__(self):
        return f"<Scope {self.kind} {getattr(self.node, 'name', '')}>"


@dataclass
class Binding:
    kind: str                 # assign | aug | for_range | decl | import | from_import | other
    node: ast.AST
    value: ast.AST | None = None
    op: ast.operator | None = None
    module: str | None = None  # for import / from_import
    attr: str | None = None    # for from_import
    stmt: ast.stmt | None = None


@dataclass(frozen=True)
class Var:
    scope: Scope
    name: str


@dataclass
class Analysis:
    tree: ast.Module
    dynamic: bool = False
    module_scope: Scope | None = None
    name_scope: dict[int, Scope] = field(default_factory=dict)
    bindings: dict[Var, list[Binding]] = field(default_factory=dict)
    var_types: dict[Var, str | None] = field(default_factory=dict)

    def __post_init__(self):
        self.dynamic = _is_dynamic(self.tree)
        self.module_scope = Scope(self.tree, "module", None)
        _Collector(self).run()
        self._resolve_bindings()
        self.all_bound_names = set()
        for sc in self._all_scopes:
            self.all_bound_names |= set(sc.raw) | sc.globals | sc.nonlocals
        self._infer_types()

    # -- resolution --------------------------------------------------------
    def resolve(self, node: ast.Name):
        """-> ("builtin", name) | ("var", Var) | ("unknown", None)"""
        if self.dynamic:
            return ("unknown", None)
        scope = self.name_scope.get(id(node))
        if scope is None:
            return ("unknown", None)
        return self._resolve_in(scope, node.id)

    def _resolve_in(self, scope: Scope, name: str):
        s = scope
        if s.kind == "class":
            if name in s.globals:
                return self._module_or_builtin(name)
            if name in s.locals:
                return ("unknown", None)
            s = s.parent
        elif s.kind in ("function", "comprehension"):
            if name in s.globals:
                return self._module_or_builtin(name)
            if name in s.locals:
                return ("var", Var(s, name))
            s = s.parent
        else:
            return self._module_or_builtin(name)
        while s is not None and s.kind != "module":
            if s.kind == "class":
                s = s.parent
                continue
            if name in s.globals:
                return self._module_or_builtin(name)
            if name in s.locals:
                return ("var", Var(s, name))
            s = s.parent
        return self._module_or_builtin(name)

    def _module_or_builtin(self, name):
        if name in self.module_scope.locals:
            return ("var", Var(self.module_scope, name))
        return ("builtin", name)

    def is_builtin(self, node, name: str | None = None) -> bool:
        if not isinstance(node, ast.Name):
            return False
        if name is not None and node.id != name:
            return False
        kind, _ = self.resolve(node)
        return kind == "builtin"

    def module_of(self, node) -> str | None:
        """If ``node`` is a Name bound only by ``import X`` -> ``"X"``."""
        if not isinstance(node, ast.Name):
            return None
        kind, var = self.resolve(node)
        if kind != "var":
            return None
        bs = self.bindings.get(var, [])
        if len(bs) == 1 and bs[0].kind == "import":
            return bs[0].module
        return None

    def from_import_of(self, node) -> tuple[str, str] | None:
        """If ``node`` is a Name bound only by ``from M import A`` -> ``(M, A)``."""
        if not isinstance(node, ast.Name):
            return None
        kind, var = self.resolve(node)
        if kind != "var":
            return None
        bs = self.bindings.get(var, [])
        if len(bs) == 1 and bs[0].kind == "from_import":
            return bs[0].module, bs[0].attr
        return None

    def qualified(self, node) -> str | None:
        """``math.sqrt`` / ``sqrt`` (from-imported) / ``sys.version_info`` -> dotted name."""
        if isinstance(node, ast.Attribute):
            base = self.qualified(node.value)
            return f"{base}.{node.attr}" if base else None
        if isinstance(node, ast.Name):
            mod = self.module_of(node)
            if mod:
                return mod
            imp = self.from_import_of(node)
            if imp:
                return f"{imp[0]}.{imp[1]}"
        return None

    # -- types -------------------------------------------------------------
    def type_of(self, expr) -> str | None:
        t = self._expr_type(expr)
        return None if t == _TOP else t

    def _resolve_bindings(self):
        scopes = self._all_scopes
        for s in scopes:
            s.locals = set(s.raw) - s.globals - s.nonlocals
        for s in scopes:
            for name, binds in s.raw.items():
                if name in s.globals:
                    owner = self.module_scope
                elif name in s.nonlocals:
                    owner = self._enclosing_owner(s, name)
                    if owner is None:
                        continue
                else:
                    owner = s
                if owner.kind == "class":
                    continue
                self.bindings.setdefault(Var(owner, name), []).extend(binds)
        # Module-level names are visible to the module too.
        self.module_scope.locals |= {
            v.name for v in self.bindings if v.scope is self.module_scope
        }

    def _enclosing_owner(self, s, name):
        p = s.parent
        while p is not None and p.kind != "module":
            if p.kind != "class" and name in p.locals:
                return p
            p = p.parent
        return None

    def _infer_types(self):
        if self.dynamic:
            return
        self.var_types = {v: _TOP for v in self.bindings}
        for _ in range(50):
            changed = False
            for var, binds in self.bindings.items():
                if self.var_types[var] is None:
                    continue
                t = self._binding_set_type(var, binds)
                if t != self.var_types[var]:
                    self.var_types[var] = t
                    changed = True
            if not changed:
                break
        else:  # did not converge: claim nothing
            self.var_types = {v: None for v in self.bindings}
            return
        # Anything still undetermined is unknown; settle once more.
        for v, t in self.var_types.items():
            if t == _TOP:
                self.var_types[v] = None
        for _ in range(50):
            changed = False
            for var, binds in self.bindings.items():
                if self.var_types[var] is None:
                    continue
                t = self._binding_set_type(var, binds)
                if t != self.var_types[var]:
                    self.var_types[var] = None if t == _TOP else t
                    changed = True
            if not changed:
                break
        else:
            self.var_types = {v: None for v in self.bindings}

    def _binding_set_type(self, var, binds):
        result = _TOP
        has_value = False
        for b in binds:
            if b.kind == "decl":
                continue
            has_value = True
            if b.kind == "assign":
                t = self._expr_type(b.value)
            elif b.kind == "aug":
                cur = self.var_types.get(var)
                t = _binop_type(cur, b.op, self._expr_type(b.value), b.value)
            elif b.kind == "for_range":
                t = INT if self.is_builtin(b.value.func, "range") else None
            else:
                t = None
            if t is None:
                return None
            if t == _TOP:
                continue
            if result == _TOP:
                result = t
            elif result != t:
                return None
        if not has_value:
            return None
        return result

    def _expr_type(self, e):
        if isinstance(e, ast.Constant):
            v = e.value
            if isinstance(v, bool):
                return BOOL
            return {int: INT, float: FLOAT, str: STR}.get(type(v))
        if isinstance(e, ast.JoinedStr):
            # f"{x}" alone returns whatever x.__format__ returns (maybe a subclass)
            if len(e.values) == 1 and isinstance(e.values[0], ast.FormattedValue):
                return None
            return STR
        if isinstance(e, (ast.List, ast.ListComp)):
            return LIST
        if isinstance(e, (ast.Dict, ast.DictComp)):
            return DICT
        if isinstance(e, (ast.Set, ast.SetComp)):
            return SET
        if isinstance(e, ast.Tuple):
            return TUPLE
        if isinstance(e, ast.Name):
            kind, var = self.resolve(e)
            if kind == "var":
                return self.var_types.get(var)
            return None
        if isinstance(e, ast.NamedExpr):
            return self._expr_type(e.value)
        if isinstance(e, ast.BinOp):
            return _binop_type(self._expr_type(e.left), e.op, self._expr_type(e.right), e.right)
        if isinstance(e, ast.UnaryOp):
            t = self._expr_type(e.operand)
            if isinstance(e.op, ast.Not):
                return BOOL
            if t == _TOP:
                return _TOP
            if t == INT:
                return INT
            if t == FLOAT and isinstance(e.op, (ast.USub, ast.UAdd)):
                return FLOAT
            return None
        if isinstance(e, ast.Compare):
            if all(isinstance(op, (ast.In, ast.NotIn, ast.Is, ast.IsNot)) for op in e.ops):
                return BOOL
            ts = [self._expr_type(x) for x in [e.left, *e.comparators]]
            if all(t in (INT, FLOAT, STR, BOOL, _TOP) for t in ts) and any(t != _TOP for t in ts):
                return BOOL
            if all(t == _TOP for t in ts):
                return _TOP
            return None
        if isinstance(e, (ast.BoolOp, ast.IfExp)):
            parts = e.values if isinstance(e, ast.BoolOp) else [e.body, e.orelse]
            return _join([self._expr_type(p) for p in parts])
        if isinstance(e, ast.Call) and not e.keywords and not any(
            isinstance(a, ast.Starred) for a in e.args
        ):
            return self._call_type(e)
        if isinstance(e, ast.Subscript):
            t = self._expr_type(e.value)
            if t == STR:
                return STR
            if t in (LIST, TUPLE) and isinstance(e.slice, ast.Slice):
                return t
            return None
        return None

    def _call_type(self, e):
        f = e.func
        if isinstance(f, ast.Name) and self.is_builtin(f):
            n, args = f.id, e.args
            if n in ("len", "ord", "int", "hash"):
                return INT
            if n == "float":
                return FLOAT
            if n in ("bool", "isinstance", "issubclass", "callable", "hasattr"):
                return BOOL
            if n in ("chr", "hex", "oct", "bin"):
                return STR
            if n in ("list", "sorted"):
                return LIST
            if n == "dict":
                return DICT
            if n == "set":
                return SET
            if n == "tuple":
                return TUPLE
            if n == "abs" and len(args) == 1:
                t = self._expr_type(args[0])
                return t if t in (INT, FLOAT, _TOP) else None
            return None
        if isinstance(f, ast.Attribute):
            recv = self._expr_type(f.value)
            if recv == STR:
                return _STR_METHOD_TYPES.get(f.attr)
            if recv == LIST and f.attr == "copy":
                return LIST
            if recv == LIST and f.attr in ("count", "index"):
                return INT
            if recv == DICT and f.attr == "copy":
                return DICT
            if recv == SET and f.attr in ("copy", "union", "intersection", "difference"):
                return SET
        return None

    @property
    def _all_scopes(self):
        seen = []
        stack = [self.module_scope]
        while stack:
            s = stack.pop()
            seen.append(s)
            stack.extend(getattr(s, "children", []))
        return seen


_STR_METHOD_TYPES = {
    **{m: STR for m in ("upper", "lower", "strip", "lstrip", "rstrip", "replace", "title",
                        "capitalize", "casefold", "swapcase", "center", "ljust", "rjust",
                        "zfill", "join", "format", "expandtabs", "removeprefix",
                        "removesuffix")},
    **{m: BOOL for m in ("startswith", "endswith", "isdigit", "isalpha", "isalnum",
                         "isspace", "isupper", "islower", "istitle", "isnumeric",
                         "isdecimal", "isidentifier", "isascii", "isprintable")},
    **{m: INT for m in ("count", "find", "rfind", "index", "rindex")},
    **{m: LIST for m in ("split", "rsplit", "splitlines")},
}

_INT_OPS = (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod, ast.LShift, ast.RShift,
            ast.BitOr, ast.BitAnd, ast.BitXor)
_FLOAT_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)


def _join(ts):
    known = [t for t in ts if t != _TOP]
    if any(t is None for t in known):
        return None
    if not known:
        return _TOP
    return known[0] if all(t == known[0] for t in known) else None


def _binop_type(lt, op, rt, right_node=None):
    if lt is None or rt is None:
        return None
    if lt == _TOP and rt == _TOP:
        return _TOP
    # Optimistically assume an undetermined operand matches the other side.
    if lt == _TOP:
        lt = rt
    if rt == _TOP:
        rt = lt
    if lt == INT and rt == INT:
        if isinstance(op, _INT_OPS):
            return INT
        if isinstance(op, ast.Div):
            return FLOAT
        if (isinstance(op, ast.Pow) and isinstance(right_node, ast.Constant)
                and type(right_node.value) is int and right_node.value >= 0):
            return INT
        return None
    if {lt, rt} <= {INT, FLOAT} and isinstance(op, _FLOAT_OPS):
        return FLOAT
    if lt == STR and rt == STR and isinstance(op, ast.Add):
        return STR
    if isinstance(op, ast.Mult) and {lt, rt} in ({STR, INT}, {LIST, INT}, {TUPLE, INT}):
        return (lt if lt != INT else rt)
    if lt == rt and lt in (LIST, TUPLE) and isinstance(op, ast.Add):
        return lt
    return None


def _is_dynamic(tree) -> bool:
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in DYNAMIC_NAMES:
            return True
        if isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names):
            return True
        if isinstance(n, (ast.Import, ast.ImportFrom)) and any(
            (a.name.split(".")[0] in ("builtins", "__main__", "importlib")) for a in n.names
        ):
            return True
        if (isinstance(n, ast.Attribute) and n.attr == "modules"
                and isinstance(n.value, ast.Name) and n.value.id == "sys"):
            return True
    return False


class _Collector:
    """Builds the scope tree and records every binding of every name."""

    def __init__(self, analysis: Analysis):
        self.a = analysis

    def run(self):
        self.a.module_scope.children = []
        self.a.module_scope.top_index = {}
        self._body(self.a.tree.body, self.a.module_scope)

    def _new_scope(self, node, kind, parent):
        s = Scope(node, kind, parent)
        s.children = []
        parent.children.append(s)
        return s

    def _bind(self, scope, name, binding):
        # A walrus inside a comprehension binds in the enclosing non-comprehension scope.
        if binding.kind != "comp_target":
            while scope.kind == "comprehension":
                scope = scope.parent
        else:
            binding.kind = "other"
        scope.raw.setdefault(name, []).append(binding)

    def _body(self, stmts, scope):
        for stmt in stmts:
            self._stmt(stmt, scope)

    def _target(self, target, scope, binding_factory):
        """Record bindings for an assignment target."""
        if isinstance(target, ast.Name):
            self.a.name_scope[id(target)] = scope
            self._bind(scope, target.id, binding_factory(target))
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._target(elt, scope, lambda n: Binding("other", n))
        elif isinstance(target, ast.Starred):
            self._target(target.value, scope, lambda n: Binding("other", n))
        else:  # attribute / subscript target: evaluate its parts
            self._expr(target, scope)

    def _stmt(self, stmt, scope):
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in stmt.decorator_list:
                self._expr(d, scope)
            self._args_outer(stmt.args, scope)
            if stmt.returns:
                self._expr(stmt.returns, scope)
            self._bind(scope, stmt.name, Binding("other", stmt, stmt=stmt))
            inner = self._new_scope(stmt, "function", scope)
            self._args_inner(stmt.args, inner)
            self._body(stmt.body, inner)
        elif isinstance(stmt, ast.ClassDef):
            for d in stmt.decorator_list:
                self._expr(d, scope)
            for b in stmt.bases:
                self._expr(b, scope)
            for k in stmt.keywords:
                self._expr(k.value, scope)
            self._bind(scope, stmt.name, Binding("other", stmt, stmt=stmt))
            inner = self._new_scope(stmt, "class", scope)
            self._body(stmt.body, inner)
        elif isinstance(stmt, ast.Assign):
            self._expr(stmt.value, scope)
            for t in stmt.targets:
                self._target(t, scope, lambda n: Binding("assign", n, stmt.value, stmt=stmt))
        elif isinstance(stmt, ast.AugAssign):
            self._expr(stmt.value, scope)
            if isinstance(stmt.target, ast.Name):
                self.a.name_scope[id(stmt.target)] = scope
                self._bind(scope, stmt.target.id,
                           Binding("aug", stmt.target, stmt.value, op=stmt.op, stmt=stmt))
            else:
                self._expr(stmt.target, scope)
        elif isinstance(stmt, ast.AnnAssign):
            self._expr(stmt.annotation, scope)
            if stmt.value is not None:
                self._expr(stmt.value, scope)
            if isinstance(stmt.target, ast.Name):
                kind = "assign" if stmt.value is not None else "decl"
                self.a.name_scope[id(stmt.target)] = scope
                self._bind(scope, stmt.target.id,
                           Binding(kind, stmt.target, stmt.value, stmt=stmt))
            else:
                self._expr(stmt.target, scope)
        elif isinstance(stmt, (ast.For, ast.AsyncFor)):
            self._expr(stmt.iter, scope)
            is_range = (isinstance(stmt, ast.For) and isinstance(stmt.target, ast.Name)
                        and isinstance(stmt.iter, ast.Call) and isinstance(stmt.iter.func, ast.Name)
                        and stmt.iter.func.id == "range" and not stmt.iter.keywords)
            self._target(stmt.target, scope,
                         lambda n: Binding("for_range" if is_range else "other", n,
                                           stmt.iter if is_range else None, stmt=stmt))
            self._body(stmt.body, scope)
            self._body(stmt.orelse, scope)
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for alias in stmt.names:
                if isinstance(stmt, ast.Import):
                    if alias.asname:
                        b = Binding("import", stmt, module=alias.name)
                        name = alias.asname
                    else:
                        name = alias.name.split(".")[0]
                        b = Binding("import", stmt, module=name)
                elif stmt.level == 0 and stmt.module:
                    name = alias.asname or alias.name
                    b = Binding("from_import", stmt, module=stmt.module, attr=alias.name)
                else:
                    name = alias.asname or alias.name
                    b = Binding("other", stmt)
                b.stmt = stmt
                self._bind(scope, name, b)
        elif isinstance(stmt, ast.Global):
            scope.globals.update(stmt.names)
        elif isinstance(stmt, ast.Nonlocal):
            scope.nonlocals.update(stmt.names)
        elif isinstance(stmt, ast.Delete):
            for t in stmt.targets:
                self._target(t, scope, lambda n: Binding("other", n))
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                self._expr(item.context_expr, scope)
                if item.optional_vars is not None:
                    self._target(item.optional_vars, scope, lambda n: Binding("other", n))
            self._body(stmt.body, scope)
        elif isinstance(stmt, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            self._body(stmt.body, scope)
            for h in stmt.handlers:
                if h.type is not None:
                    self._expr(h.type, scope)
                if h.name:
                    self._bind(scope, h.name, Binding("other", h))
                self._body(h.body, scope)
            self._body(stmt.orelse, scope)
            self._body(stmt.finalbody, scope)
        elif isinstance(stmt, ast.Match):
            self._expr(stmt.subject, scope)
            for case in stmt.cases:
                for sub in ast.walk(case.pattern):
                    name = getattr(sub, "name", None) if isinstance(
                        sub, (ast.MatchAs, ast.MatchStar)) else None
                    if isinstance(sub, ast.MatchMapping) and sub.rest:
                        name = sub.rest
                    if name:
                        self._bind(scope, name, Binding("other", sub))
                    if isinstance(sub, ast.MatchValue):
                        self._expr(sub.value, scope)
                    if isinstance(sub, ast.MatchClass):
                        self._expr(sub.cls, scope)
                if case.guard is not None:
                    self._expr(case.guard, scope)
                self._body(case.body, scope)
        else:
            # If / While / Expr / Return / Raise / Assert / Pass / ...
            for name, value in ast.iter_fields(stmt):
                if isinstance(value, list):
                    if value and isinstance(value[0], ast.stmt):
                        self._body(value, scope)
                    else:
                        for v in value:
                            if isinstance(v, ast.expr):
                                self._expr(v, scope)
                elif isinstance(value, ast.expr):
                    self._expr(value, scope)

    def _args_outer(self, args, scope):
        for d in args.defaults + [d for d in args.kw_defaults if d is not None]:
            self._expr(d, scope)
        for a in args.posonlyargs + args.args + args.kwonlyargs + [
            x for x in (args.vararg, args.kwarg) if x
        ]:
            if a.annotation is not None:
                self._expr(a.annotation, scope)

    def _args_inner(self, args, inner):
        for a in args.posonlyargs + args.args + args.kwonlyargs + [
            x for x in (args.vararg, args.kwarg) if x
        ]:
            self._bind(inner, a.arg, Binding("other", a))

    def _expr(self, e, scope):
        if isinstance(e, ast.Name):
            self.a.name_scope[id(e)] = scope
            if not isinstance(e.ctx, ast.Load):
                self._bind(scope, e.id, Binding("other", e))
            return
        if isinstance(e, ast.NamedExpr):
            self._expr(e.value, scope)
            self.a.name_scope[id(e.target)] = scope
            self._bind(scope, e.target.id, Binding("assign", e.target, e.value))
            return
        if isinstance(e, ast.Lambda):
            self._args_outer(e.args, scope)
            inner = self._new_scope(e, "function", scope)
            self._args_inner(e.args, inner)
            self._expr(e.body, inner)
            return
        if isinstance(e, _COMPS):
            first = e.generators[0]
            self._expr(first.iter, scope)
            inner = self._new_scope(e, "comprehension", scope)
            for i, gen in enumerate(e.generators):
                if i:
                    self._expr(gen.iter, inner)
                is_range = (isinstance(gen.target, ast.Name) and isinstance(gen.iter, ast.Call)
                            and isinstance(gen.iter.func, ast.Name) and gen.iter.func.id == "range"
                            and not gen.iter.keywords and not gen.is_async)
                if is_range:
                    self.a.name_scope[id(gen.target)] = inner
                    b = Binding("for_range", gen.target, gen.iter)
                    inner.raw.setdefault(gen.target.id, []).append(b)
                else:
                    for sub in ast.walk(gen.target):
                        if isinstance(sub, ast.Name):
                            self.a.name_scope[id(sub)] = inner
                            inner.raw.setdefault(sub.id, []).append(Binding("other", sub))
                for cond in gen.ifs:
                    self._expr(cond, inner)
            if isinstance(e, ast.DictComp):
                self._expr(e.key, inner)
                self._expr(e.value, inner)
            else:
                self._expr(e.elt, inner)
            return
        for child in ast.iter_child_nodes(e):
            if isinstance(child, ast.expr):
                self._expr(child, scope)
            elif isinstance(child, ast.comprehension):
                pass
            else:
                for sub in ast.iter_child_nodes(child):
                    if isinstance(sub, ast.expr):
                        self._expr(sub, scope)
