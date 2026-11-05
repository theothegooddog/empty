"""Shared machinery for optimization passes."""

from __future__ import annotations

import ast
import math

from ..registry import Context

MAX_SEQ = 256           # longest str/bytes/tuple/list we inline
MAX_INT_BITS = 1024     # largest int we inline
MAX_ARG = 10_000        # largest width/count argument we evaluate at compile time

FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
SCOPE_NODES = FUNC_NODES + (ast.ClassDef,)


def is_small(value) -> bool:
    if value is None or value is Ellipsis or isinstance(value, bool):
        return True
    if isinstance(value, int):
        return value.bit_length() <= MAX_INT_BITS
    if isinstance(value, float):
        return not math.isnan(value)
    if isinstance(value, complex):
        return not (math.isnan(value.real) or math.isnan(value.imag))
    if isinstance(value, (str, bytes)):
        return len(value) <= MAX_SEQ
    if isinstance(value, (tuple, list, set, frozenset)):
        return len(value) <= MAX_SEQ and all(is_small(v) for v in value)
    return False


def const_value(node, containers: bool = False):
    """``(True, value)`` if ``node`` is a literal; lists/sets only if ``containers``."""
    if isinstance(node, ast.Constant):
        return True, node.value
    if isinstance(node, ast.Tuple) and isinstance(node.ctx, ast.Load):
        vals = []
        for elt in node.elts:
            ok, v = const_value(elt)
            if not ok:
                return False, None
            vals.append(v)
        return True, tuple(vals)
    if containers and isinstance(node, (ast.List, ast.Set)):
        vals = []
        for elt in node.elts:
            ok, v = const_value(elt)
            if not ok:
                return False, None
            vals.append(v)
        if isinstance(node, ast.Set):
            try:
                return True, set(vals)
            except TypeError:
                return False, None
        return True, vals
    return False, None


def has_unordered_text(value) -> bool:
    """Sets of str/bytes iterate in an order that depends on PYTHONHASHSEED."""
    if isinstance(value, (set, frozenset)):
        return any(isinstance(v, (str, bytes, tuple)) for v in value)
    if isinstance(value, (tuple, list)):
        return any(has_unordered_text(v) for v in value)
    return False


def make_node(value, like: ast.AST) -> ast.expr:
    if isinstance(value, tuple):
        node = ast.Tuple(elts=[make_node(v, like) for v in value], ctx=ast.Load())
    elif isinstance(value, list):
        node = ast.List(elts=[make_node(v, like) for v in value], ctx=ast.Load())
    elif isinstance(value, set):
        if not value:
            raise ValueError("empty set has no literal")
        node = ast.Set(elts=[make_node(v, like) for v in sorted(value, key=repr)])
    else:
        node = ast.Constant(value=value)
    return ast.copy_location(node, like)


def can_emit(value) -> bool:
    if isinstance(value, set) and not value:
        return False
    if isinstance(value, frozenset):
        return False
    if isinstance(value, (tuple, list, set)):
        return all(can_emit(v) for v in value)
    return is_small(value)


def is_docstring(stmt, index) -> bool:
    return (index == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str))


def name(id_: str, like=None) -> ast.Name:
    n = ast.Name(id=id_, ctx=ast.Load())
    return ast.copy_location(n, like) if like is not None else n


def call(func: ast.expr, args, like) -> ast.Call:
    return ast.copy_location(ast.Call(func=func, args=list(args), keywords=[]), like)


def simple_call(node, fname: str, a, nargs=None) -> bool:
    """``node`` is ``fname(...)`` with ``fname`` the builtin and no keywords/stars."""
    if not (isinstance(node, ast.Call) and a.is_builtin(node.func, fname)):
        return False
    if node.keywords or any(isinstance(x, ast.Starred) for x in node.args):
        return False
    return nargs is None or len(node.args) == nargs


class Pass(ast.NodeTransformer):
    """Base class: knows the context and how to record a rewrite."""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.a = ctx.analysis
        self.changed = False

    def on(self, technique: str) -> bool:
        return self.ctx.enabled(technique)

    def did(self, technique: str, new, old=None):
        self.ctx.report.bump(technique)
        self.changed = True
        if old is not None and isinstance(new, ast.AST) and not hasattr(new, "lineno"):
            ast.copy_location(new, old)
        return new

    def builtin_free(self, fname: str) -> bool:
        """True if ``fname`` is never rebound anywhere, so a new ``fname`` Name is the builtin."""
        return not self.a.dynamic and fname not in self.a.all_bound_names

    # --- boolean ("test") contexts ---------------------------------------
    # Expressions whose value is only ever used for its truthiness.
    def rewrite_test(self, expr):
        return expr

    def _test(self, expr):
        if isinstance(expr, ast.BoolOp):
            expr.values = [self._test(v) for v in expr.values]
        elif isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
            expr.operand = self._test(expr.operand)
        for _ in range(4):
            new = self.rewrite_test(expr)
            if new is expr:
                break
            expr = new
        return expr

    def visit_If(self, node):
        self.generic_visit(node)
        node.test = self._test(node.test)
        return self.after_if(node)

    def after_if(self, node):
        return node

    def visit_While(self, node):
        self.generic_visit(node)
        node.test = self._test(node.test)
        return self.after_while(node)

    def after_while(self, node):
        return node

    def visit_IfExp(self, node):
        self.generic_visit(node)
        node.test = self._test(node.test)
        return self.after_ifexp(node)

    def after_ifexp(self, node):
        return node

    def visit_Assert(self, node):
        self.generic_visit(node)
        node.test = self._test(node.test)
        return self.after_assert(node)

    def after_assert(self, node):
        return node

    def visit_comprehension(self, node):
        self.generic_visit(node)
        node.ifs = [self._test(c) for c in node.ifs]
        return node
