"""Dead-code elimination and constant propagation."""

from __future__ import annotations

import ast

from ..analysis import Var
from ..registry import technique
from .base import FUNC_NODES, Pass, const_value, is_docstring, is_small

T_IF = technique("dce.if-constant", 1, "dead code", "`if <literal>:` keeps only the branch that runs")
T_WHILE = technique("dce.while-false", 1, "dead code", "`while <falsy literal>:` -> its else block")
T_AFTER = {
    ast.Return: technique("dce.after-return", 1, "dead code", "drop statements after `return`"),
    ast.Raise: technique("dce.after-raise", 1, "dead code", "drop statements after `raise`"),
    ast.Break: technique("dce.after-break", 1, "dead code", "drop statements after `break`"),
    ast.Continue: technique("dce.after-continue", 1, "dead code", "drop statements after `continue`"),
}
T_INFINITE = technique("dce.after-infinite-loop", 1, "dead code",
                       "drop statements after a `while True:` that never breaks")
T_FOR_EMPTY = technique("dce.for-empty", 1, "dead code", "`for x in ():` -> its else block")
T_ASSERT = technique("dce.assert-true", 1, "dead code", "drop `assert <truthy literal>`")
T_TRY_PASS = technique("dce.try-pass", 1, "dead code",
                       "`try: pass` can't raise: drop its except handlers")
T_PASS = technique("dce.redundant-pass", 1, "dead code", "drop `pass` from non-empty blocks")
T_EMPTY_ELSE = technique("dce.empty-else", 1, "dead code", "drop `else: pass`")
T_CONST_EXPR = technique("dce.constant-expression", 1, "dead code",
                         "drop literal expression statements (not docstrings)")
T_MODULE_CONST = technique("prop.module-constant", 1, "constant propagation",
                           "inline module-level `UPPER_CASE = <literal>` that is never rebound")
T_LOCAL_CONST = technique("prop.local-constant", 1, "constant propagation",
                          "inline a function local assigned a literal once and never rebound")


def _contains(stmts, types) -> bool:
    return any(isinstance(sub, types) for s in stmts for sub in ast.walk(s))


def _has_break(loop) -> bool:
    """Does a `break` exit *this* loop (ignoring nested loops and functions)?"""
    stack = list(loop.body)
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Break):
            return True
        if isinstance(n, (ast.For, ast.AsyncFor, ast.While, *FUNC_NODES, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(n))
    return False


class DeadCode(Pass):

    def __init__(self, ctx):
        super().__init__(ctx)
        self.function_depth = 0

    def _can_drop(self, stmts) -> bool:
        if _contains(stmts, (ast.Yield, ast.YieldFrom, ast.Await, ast.Global, ast.Nonlocal)):
            return False  # would change generator-ness or scoping
        if any(isinstance(n, ast.Name) and n.id in ("super", "__class__")
               for s in stmts for n in ast.walk(s)):
            return False
        if self.function_depth:
            # Removing an assignment could turn a local into a global lookup.
            for s in stmts:
                for n in ast.walk(s):
                    if isinstance(n, ast.Name) and not isinstance(n.ctx, ast.Load):
                        return False
                    if isinstance(n, (ast.Import, ast.ImportFrom, ast.ExceptHandler,
                                      ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                      ast.MatchAs, ast.MatchStar, ast.MatchMapping)):
                        return False
        return True

    def _block(self, stmts, docstring_ok=False):
        out = []
        for i, stmt in enumerate(stmts):
            new = self.visit(stmt)
            if new is None:
                continue
            new_list = new if isinstance(new, list) else [new]
            for s in new_list:
                if (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                        and not (docstring_ok and is_docstring(s, len(out)))
                        and self.on(T_CONST_EXPR)):
                    self.did(T_CONST_EXPR, None)
                    continue
                out.append(s)
            last = out[-1] if out else None
            rest = stmts[i + 1:]
            if not rest or last is None:
                continue
            tech = None
            if type(last) in T_AFTER and new_list and new_list[-1] is last:
                tech = T_AFTER[type(last)]
            elif (isinstance(last, ast.While) and new_list and new_list[-1] is last
                  and isinstance(last.test, ast.Constant) and last.test.value
                  and not _has_break(last)):
                tech = T_INFINITE
            if tech and self.on(tech) and self._can_drop(rest):
                for _ in rest:
                    self.did(tech, None)
                break
        # `pass` is only needed when it is the whole block.
        if len(out) > 1 and self.on(T_PASS):
            kept = [s for s in out if not isinstance(s, ast.Pass)] or out[:1]
            for _ in range(len(out) - len(kept)):
                self.did(T_PASS, None)
            out = kept
        return out

    def generic_visit(self, node):
        docstring_ok = isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                         ast.ClassDef))
        for fname, value in ast.iter_fields(node):
            if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                setattr(node, fname, self._block(value, docstring_ok and fname == "body"))
            elif isinstance(value, list):
                setattr(node, fname, [self.visit(v) if isinstance(v, ast.AST) else v for v in value])
            elif isinstance(value, ast.AST):
                setattr(node, fname, self.visit(value))
        for fname in ("orelse", "finalbody"):
            block = getattr(node, fname, None)
            if (isinstance(block, list) and len(block) == 1 and isinstance(block[0], ast.Pass)
                    and not (isinstance(node, ast.Try) and fname == "finalbody"
                             and not node.handlers)
                    and self.on(T_EMPTY_ELSE)):
                setattr(node, fname, [])
                self.did(T_EMPTY_ELSE, None)
        return node

    def _scope(self, node):
        self.function_depth += 1
        try:
            self.generic_visit(node)
        finally:
            self.function_depth -= 1
        return node

    visit_FunctionDef = visit_AsyncFunctionDef = visit_Lambda = _scope

    def after_if(self, node):
        ok, v = const_value(node.test)
        if not ok or not self.on(T_IF):
            return node
        keep, drop = (node.body, node.orelse) if v else (node.orelse, node.body)
        if not self._can_drop(drop):
            return node
        return self.did(T_IF, keep or None)

    def after_while(self, node):
        ok, v = const_value(node.test)
        if ok and not v and self.on(T_WHILE) and self._can_drop(node.body):
            return self.did(T_WHILE, node.orelse or None)
        return node

    def visit_For(self, node):
        self.generic_visit(node)
        empty = (isinstance(node.iter, ast.Constant) and node.iter.value in ("", b"", ())) or (
            isinstance(node.iter, (ast.List, ast.Tuple)) and not node.iter.elts)
        if not (empty and self.on(T_FOR_EMPTY) and self._can_drop(node.body)):
            return node
        # The body never runs, so the loop target is never bound either.
        target_binding = ast.Assign(targets=[node.target], value=ast.Constant(0))
        if not self._can_drop([target_binding]):
            return node
        return self.did(T_FOR_EMPTY, node.orelse or None)

    def after_assert(self, node):
        ok, v = const_value(node.test)
        if ok and v and self.on(T_ASSERT):
            return self.did(T_ASSERT, None)
        return node

    def visit_Try(self, node):
        self.generic_visit(node)
        if (all(isinstance(s, ast.Pass) for s in node.body) and node.handlers
                and self.on(T_TRY_PASS) and self._can_drop(
                    [s for h in node.handlers for s in h.body])):
            if not self.function_depth or not any(h.name for h in node.handlers):
                self.did(T_TRY_PASS, None)
                if node.finalbody:
                    return ast.copy_location(
                        ast.Try(body=node.orelse or [ast.Pass()], handlers=[], orelse=[],
                                finalbody=node.finalbody), node)
                return node.orelse or None
        return node


class Propagation(Pass):
    """Replace reads of never-rebound literal variables with the literal."""

    def run(self, tree):
        if self.a.dynamic:
            return tree
        for var, binds in self.a.bindings.items():
            if len(binds) != 1 or binds[0].kind != "assign" or binds[0].stmt is None:
                continue
            stmt = binds[0].stmt
            if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                continue
            ok, value = const_value(binds[0].value)
            if not ok or not is_small(value) or (isinstance(value, str) and len(value) > 64):
                continue
            owner = var.scope
            if owner.kind == "module":
                if not var.name.isupper():
                    continue
                tech, body = T_MODULE_CONST, owner.node.body
            elif owner.kind == "function" and not isinstance(owner.node, ast.Lambda):
                tech, body = T_LOCAL_CONST, owner.node.body
            else:
                continue
            if not self.on(tech):
                continue
            try:
                k = next(i for i, s in enumerate(body) if s is stmt)
            except StopIteration:
                continue  # assigned inside an if/loop/try: not unconditional
            for later in body[k + 1:]:
                self._replace_in(later, var, value, tech)
        return tree

    def _replace_in(self, stmt, var, value, tech):
        a = self.a
        for parent in ast.walk(stmt):
            for fname, child in ast.iter_fields(parent):
                if isinstance(child, ast.Name):
                    if self._is_use(child, var):
                        setattr(parent, fname, self._const(value, child, tech))
                elif isinstance(child, list):
                    for i, c in enumerate(child):
                        if isinstance(c, ast.Name) and self._is_use(c, var):
                            child[i] = self._const(value, c, tech)

    def _is_use(self, node, var):
        if not isinstance(node.ctx, ast.Load):
            return False
        kind, v = self.a.resolve(node)
        return kind == "var" and v == var

    def _const(self, value, like, tech):
        self.did(tech, None)
        from .base import make_node
        return make_node(value, like)
