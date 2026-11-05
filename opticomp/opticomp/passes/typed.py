"""Algebraic simplifications that are only valid for exact builtin types.

``x + 0 -> x`` is wrong in general (a custom class can do anything in
``__add__``, and ``True + 0`` is ``1``, not ``True``), so these rewrites only
fire when the analysis proves the operand's exact type.
"""

from __future__ import annotations

import ast

from ..analysis import BOOL, DICT, FLOAT, INT, LIST, SET, STR, TUPLE
from ..registry import technique
from .base import Pass, const_value, simple_call

_I = {}  # int rules
for _n, _d in [
    ("add-zero", "`n + 0` / `0 + n` -> `n`"), ("sub-zero", "`n - 0` -> `n`"),
    ("zero-sub", "`0 - n` -> `-n`"), ("mul-one", "`n * 1` / `1 * n` -> `n`"),
    ("floordiv-one", "`n // 1` -> `n`"), ("pow-one", "`n ** 1` -> `n`"),
    ("pow-two", "`n ** 2` -> `n * n`"), ("pow-three", "`n ** 3` -> `n * n * n`"),
    ("or-zero", "`n | 0` -> `n`"), ("xor-zero", "`n ^ 0` -> `n`"),
    ("and-minus-one", "`n & -1` -> `n`"), ("lshift-zero", "`n << 0` -> `n`"),
    ("rshift-zero", "`n >> 0` -> `n`"), ("double-negation", "`-(-n)` -> `n`"),
    ("double-invert", "`~~n` -> `n`"), ("unary-plus", "`+n` -> `n`"),
    ("int-call-identity", "`int(n)` -> `n`"), ("abs-abs", "`abs(abs(n))` -> `abs(n)`"),
    ("zero-test", "`n == 0` -> `not n`"), ("nonzero-test", "`if n != 0:` -> `if n:`"),
    ("membership-set", "`n in (1, 2, 3)` -> `n in {1, 2, 3}` (hash lookup)"),
]:
    _I[_n] = technique(f"typed.int.{_n}", 1, "type-aware", f"for a known int n: {_d}")
_F = {}
for _n, _d in [
    ("mul-one", "`x * 1.0` -> `x`"), ("div-one", "`x / 1.0` -> `x`"),
    ("sub-zero", "`x - 0.0` -> `x`"), ("pow-one", "`x ** 1` -> `x`"),
    ("float-call-identity", "`float(x)` -> `x`"), ("unary-plus", "`+x` -> `x`"),
]:
    _F[_n] = technique(f"typed.float.{_n}", 1, "type-aware", f"for a known float x: {_d}")
_S = {}
for _n, _d in [
    ("add-empty", "`s + ''` / `'' + s` -> `s`"), ("mul-one", "`s * 1` -> `s`"),
    ("fstring-identity", "`f'{s}'` -> `s`"), ("str-call-identity", "`str(s)` -> `s`"),
    ("membership-set", "`s in ('a', 'b', 'c')` -> `s in {'a', 'b', 'c'}`"),
]:
    _S[_n] = technique(f"typed.str.{_n}", 1, "type-aware", f"for a known str s: {_d}")
_B = {}
for _n, _d in [
    ("eq-true", "`b == True` -> `b`"), ("eq-false", "`b == False` -> `not b`"),
    ("ne-true", "`b != True` -> `not b`"), ("ne-false", "`b != False` -> `b`"),
    ("is-true", "`b is True` -> `b`"), ("is-false", "`b is False` -> `not b`"),
    ("bool-call-identity", "`bool(b)` -> `b`"), ("not-not", "`not not b` -> `b`"),
]:
    _B[_n] = technique(f"typed.bool.{_n}", 1, "type-aware", f"for a known bool b: {_d}")
_C = {}
for _n, _d in [
    ("len-test", "`if len(c):` -> `if c:`"),
    ("len-eq-zero", "`len(c) == 0` -> `not c`"),
    ("len-nonzero-test", "`if len(c) > 0:` / `!= 0` / `>= 1` -> `if c:`"),
    ("empty-eq", "`c == ''` / `[]` / `()` / `{}` -> `not c`"),
    ("empty-ne-test", "`if c != '':` -> `if c:`"),
    ("tuple-call-identity", "`tuple(t)` -> `t` for a known tuple"),
]:
    _C[_n] = technique(f"typed.container.{_n}", 1, "type-aware",
                       f"for a known str/list/dict/set/tuple c: {_d}")

_CONTAINERS = (STR, LIST, DICT, SET, TUPLE)


def _is_int_const(node, *values):
    return (isinstance(node, ast.Constant) and type(node.value) is int
            and (not values or node.value in values))


def _is_num_const(node, value):
    return (isinstance(node, ast.Constant) and type(node.value) in (int, float)
            and node.value == value)


def _not(expr, like):
    return ast.copy_location(ast.UnaryOp(op=ast.Not(), operand=expr), like)


def _mul(x, times, like):
    out = x
    for _ in range(times - 1):
        out = ast.BinOp(left=out, op=ast.Mult(), right=ast.Name(id=x.id, ctx=ast.Load()))
    return ast.copy_location(out, like)


def _empty_literal_matches(node, t):
    if isinstance(node, ast.Constant):
        return (t == STR and node.value == "" and type(node.value) is str) or (
            t == TUPLE and node.value == ())
    if isinstance(node, ast.List):
        return t == LIST and not node.elts
    if isinstance(node, ast.Dict):
        return t == DICT and not node.keys
    if isinstance(node, ast.Tuple):
        return t == TUPLE and not node.elts
    return False


class Typed(Pass):

    def T(self, node):
        return self.a.type_of(node)

    def visit_BinOp(self, node):
        self.generic_visit(node)
        l, r, op = node.left, node.right, node.op
        lt, rt = self.T(l), self.T(r)

        if lt == INT or rt == INT:
            rule = None
            if isinstance(op, ast.Add):
                if lt == INT and _is_int_const(r, 0):
                    rule = ("add-zero", l)
                elif rt == INT and _is_int_const(l, 0):
                    rule = ("add-zero", r)
            elif isinstance(op, ast.Sub):
                if lt == INT and _is_int_const(r, 0):
                    rule = ("sub-zero", l)
                elif rt == INT and _is_int_const(l, 0):
                    rule = ("zero-sub", ast.copy_location(ast.UnaryOp(op=ast.USub(), operand=r), node))
            elif isinstance(op, ast.Mult):
                if lt == INT and _is_int_const(r, 1):
                    rule = ("mul-one", l)
                elif rt == INT and _is_int_const(l, 1):
                    rule = ("mul-one", r)
            elif isinstance(op, ast.FloorDiv) and lt == INT and _is_int_const(r, 1):
                rule = ("floordiv-one", l)
            elif isinstance(op, ast.Pow) and lt == INT:
                if _is_int_const(r, 1):
                    rule = ("pow-one", l)
                elif _is_int_const(r, 2) and isinstance(l, ast.Name):
                    rule = ("pow-two", _mul(l, 2, node))
                elif _is_int_const(r, 3) and isinstance(l, ast.Name):
                    rule = ("pow-three", _mul(l, 3, node))
            elif isinstance(op, (ast.BitOr, ast.BitXor)):
                n = "or-zero" if isinstance(op, ast.BitOr) else "xor-zero"
                if lt == INT and _is_int_const(r, 0):
                    rule = (n, l)
                elif rt == INT and _is_int_const(l, 0):
                    rule = (n, r)
            elif isinstance(op, ast.BitAnd):
                if lt == INT and _is_int_const(r, -1):
                    rule = ("and-minus-one", l)
                elif rt == INT and _is_int_const(l, -1):
                    rule = ("and-minus-one", r)
            elif isinstance(op, (ast.LShift, ast.RShift)) and lt == INT and _is_int_const(r, 0):
                rule = ("lshift-zero" if isinstance(op, ast.LShift) else "rshift-zero", l)
            if rule and self.on(_I[rule[0]]):
                return self.did(_I[rule[0]], rule[1], node)

        if lt == FLOAT:
            rule = None
            if isinstance(op, ast.Mult) and _is_num_const(r, 1):
                rule = ("mul-one", l)
            elif isinstance(op, ast.Div) and _is_num_const(r, 1):
                rule = ("div-one", l)
            elif isinstance(op, ast.Sub) and _is_num_const(r, 0):
                rule = ("sub-zero", l)
            elif isinstance(op, ast.Pow) and _is_int_const(r, 1):
                rule = ("pow-one", l)
            if rule and self.on(_F[rule[0]]):
                return self.did(_F[rule[0]], rule[1], node)
        if rt == FLOAT and isinstance(op, ast.Mult) and _is_num_const(l, 1) \
                and self.on(_F["mul-one"]):
            return self.did(_F["mul-one"], r, node)

        if lt == STR or rt == STR:
            empty = lambda n: isinstance(n, ast.Constant) and n.value == "" and type(n.value) is str
            if isinstance(op, ast.Add) and self.on(_S["add-empty"]):
                if lt == STR and empty(r):
                    return self.did(_S["add-empty"], l, node)
                if rt == STR and empty(l):
                    return self.did(_S["add-empty"], r, node)
            if isinstance(op, ast.Mult) and lt == STR and _is_int_const(r, 1) and self.on(_S["mul-one"]):
                return self.did(_S["mul-one"], l, node)
        return node

    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        inner = node.operand
        t = self.T(inner)
        if isinstance(node.op, ast.UAdd):
            if t == INT and self.on(_I["unary-plus"]):
                return self.did(_I["unary-plus"], inner, node)
            if t == FLOAT and self.on(_F["unary-plus"]):
                return self.did(_F["unary-plus"], inner, node)
        if isinstance(inner, ast.UnaryOp) and type(inner.op) is type(node.op):
            tt = self.T(inner.operand)
            if isinstance(node.op, ast.USub) and tt == INT and self.on(_I["double-negation"]):
                return self.did(_I["double-negation"], inner.operand, node)
            if isinstance(node.op, ast.Invert) and tt == INT and self.on(_I["double-invert"]):
                return self.did(_I["double-invert"], inner.operand, node)
            if isinstance(node.op, ast.Not) and tt == BOOL and self.on(_B["not-not"]):
                return self.did(_B["not-not"], inner.operand, node)
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        for fname, ty, tech in (("int", INT, _I["int-call-identity"]),
                                ("float", FLOAT, _F["float-call-identity"]),
                                ("str", STR, _S["str-call-identity"]),
                                ("bool", BOOL, _B["bool-call-identity"]),
                                ("tuple", TUPLE, _C["tuple-call-identity"])):
            if simple_call(node, fname, self.a, 1) and self.T(node.args[0]) == ty and self.on(tech):
                return self.did(tech, node.args[0], node)
        if (simple_call(node, "abs", self.a, 1) and simple_call(node.args[0], "abs", self.a, 1)
                and self.T(node.args[0].args[0]) in (INT, FLOAT) and self.on(_I["abs-abs"])):
            return self.did(_I["abs-abs"], node.args[0], node)
        return node

    def visit_JoinedStr(self, node):
        self.generic_visit(node)
        if len(node.values) == 1 and isinstance(node.values[0], ast.FormattedValue):
            fv = node.values[0]
            if fv.conversion == -1 and fv.format_spec is None and self.T(fv.value) == STR \
                    and self.on(_S["fstring-identity"]):
                return self.did(_S["fstring-identity"], fv.value, node)
        return node

    def _len_arg(self, node):
        """``len(c)`` for a known container ``c`` -> ``c``."""
        if simple_call(node, "len", self.a, 1) and self.T(node.args[0]) in _CONTAINERS:
            return node.args[0]
        return None

    def visit_Compare(self, node):
        self.generic_visit(node)
        if len(node.ops) != 1:
            return node
        op, l, r = node.ops[0], node.left, node.comparators[0]
        lt, rt = self.T(l), self.T(r)

        # bool == True ...
        if lt == BOOL and isinstance(r, ast.Constant) and isinstance(r.value, bool):
            v = r.value
            key = {(ast.Eq, True): "eq-true", (ast.Eq, False): "eq-false",
                   (ast.NotEq, True): "ne-true", (ast.NotEq, False): "ne-false",
                   (ast.Is, True): "is-true", (ast.Is, False): "is-false"}.get((type(op), v))
            if key and self.on(_B[key]):
                keep = key in ("eq-true", "ne-false", "is-true")
                return self.did(_B[key], l if keep else _not(l, node), node)

        if isinstance(op, ast.Eq):
            c = self._len_arg(l)
            if c is not None and _is_int_const(r, 0) and self.on(_C["len-eq-zero"]):
                return self.did(_C["len-eq-zero"], _not(c, node), node)
            if lt in _CONTAINERS and _empty_literal_matches(r, lt) and self.on(_C["empty-eq"]):
                return self.did(_C["empty-eq"], _not(l, node), node)
            if lt == INT and _is_int_const(r, 0) and self.on(_I["zero-test"]):
                return self.did(_I["zero-test"], _not(l, node), node)

        ok, values = const_value(r)
        if (isinstance(op, (ast.In, ast.NotIn)) and ok and isinstance(values, tuple)
                and len(values) >= 3):
            if lt == INT and all(type(v) is int for v in values):
                tech = _I["membership-set"]
            elif lt == STR and all(type(v) is str for v in values):
                tech = _S["membership-set"]
            else:
                tech = None
            if tech and self.on(tech):
                node.comparators = [ast.copy_location(
                    ast.Set(elts=[ast.Constant(v) for v in values]), r)]
                return self.did(tech, node)
        return node

    def rewrite_test(self, expr):
        c = self._len_arg(expr)
        if c is not None and self.on(_C["len-test"]):
            return self.did(_C["len-test"], c)
        if isinstance(expr, ast.Compare) and len(expr.ops) == 1:
            op, l, r = expr.ops[0], expr.left, expr.comparators[0]
            c = self._len_arg(l)
            if c is not None and self.on(_C["len-nonzero-test"]) and (
                (isinstance(op, (ast.NotEq, ast.Gt)) and _is_int_const(r, 0))
                or (isinstance(op, ast.GtE) and _is_int_const(r, 1))
            ):
                return self.did(_C["len-nonzero-test"], c)
            lt = self.T(l)
            if isinstance(op, ast.NotEq):
                if lt in _CONTAINERS and _empty_literal_matches(r, lt) and self.on(_C["empty-ne-test"]):
                    return self.did(_C["empty-ne-test"], l)
                if lt == INT and _is_int_const(r, 0) and self.on(_I["nonzero-test"]):
                    return self.did(_I["nonzero-test"], l)
        return expr
