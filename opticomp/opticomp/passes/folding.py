"""Constant folding: compute at compile time anything built only from literals.

Covers operators, pure builtins, methods of str/bytes/int/float literals,
``math`` functions and constants, and well-known module constants such as
``sys.platform`` or ``typing.TYPE_CHECKING``. Every evaluation is guarded
against blowing up in size or time; if evaluation raises, the expression is
left alone so the error still happens at runtime.
"""

from __future__ import annotations

import ast
import builtins
import math
import os
import re
import string
import sys

from ..registry import technique
from .base import (MAX_ARG, Pass, can_emit, const_value, has_unordered_text, is_small,
                   make_node)

# --- operators ---------------------------------------------------------------

BINOPS = {
    ast.Add: ("add", lambda a, b: a + b), ast.Sub: ("sub", lambda a, b: a - b),
    ast.Mult: ("mul", lambda a, b: a * b), ast.Div: ("truediv", lambda a, b: a / b),
    ast.FloorDiv: ("floordiv", lambda a, b: a // b), ast.Mod: ("mod", lambda a, b: a % b),
    ast.Pow: ("pow", lambda a, b: a ** b), ast.LShift: ("lshift", lambda a, b: a << b),
    ast.RShift: ("rshift", lambda a, b: a >> b), ast.BitOr: ("bitor", lambda a, b: a | b),
    ast.BitXor: ("bitxor", lambda a, b: a ^ b), ast.BitAnd: ("bitand", lambda a, b: a & b),
}
UNARYOPS = {
    ast.UAdd: ("pos", lambda a: +a), ast.USub: ("neg", lambda a: -a),
    ast.Not: ("not", lambda a: not a), ast.Invert: ("invert", lambda a: ~a),
}
CMPOPS = {
    ast.Eq: ("eq", lambda a, b: a == b), ast.NotEq: ("ne", lambda a, b: a != b),
    ast.Lt: ("lt", lambda a, b: a < b), ast.LtE: ("le", lambda a, b: a <= b),
    ast.Gt: ("gt", lambda a, b: a > b), ast.GtE: ("ge", lambda a, b: a >= b),
    ast.In: ("in", lambda a, b: a in b), ast.NotIn: ("not-in", lambda a, b: a not in b),
    ast.Is: ("is", lambda a, b: a is b), ast.IsNot: ("is-not", lambda a, b: a is not b),
}
_SINGLETONS = (type(None), bool, type(Ellipsis))

for _op, (_n, _) in BINOPS.items():
    technique(f"fold.{_n}", 1, "constant folding", f"evaluate `{_n}` of two literals")
for _op, (_n, _) in UNARYOPS.items():
    technique(f"fold.{_n}", 1, "constant folding", f"evaluate unary `{_n}` of a literal")
for _op, (_n, _) in CMPOPS.items():
    technique(f"fold.cmp-{_n}", 1, "constant folding", f"evaluate `{_n}` comparison of literals")
T_AND = technique("fold.and", 1, "constant folding", "simplify `and` with literal operands")
T_OR = technique("fold.or", 1, "constant folding", "simplify `or` with literal operands")
T_IFEXP = technique("fold.ifexp", 1, "constant folding", "`a if <literal> else b` -> one branch")
T_INDEX = technique("fold.index", 1, "constant folding", '`"abc"[1]`, `(1, 2)[0]` -> literal')
T_SLICE = technique("fold.slice", 1, "constant folding", '`"abcdef"[1:3]` -> literal')
T_FSTRING = technique("fold.fstring", 1, "constant folding", "f-string of literals -> str")
T_TRUTH = technique("fold.literal-truthiness", 1, "constant folding",
                    "`if []:` / `if [1, 2]:` in a test -> False / True")

# --- builtins ----------------------------------------------------------------

PURE_BUILTINS = ["abs", "all", "any", "ascii", "bin", "bool", "bytes", "callable", "chr",
                 "complex", "divmod", "float", "hex", "int", "isinstance", "len", "list",
                 "max", "min", "oct", "ord", "pow", "repr", "round", "set", "sorted", "str",
                 "sum", "tuple", "format"]
for _b in PURE_BUILTINS:
    technique(f"fold.builtin.{_b}", 1, "builtin folding", f"evaluate `{_b}(...)` on literals")
# These accept sets of strings because their result doesn't depend on iteration order.
_ORDER_FREE = {"len", "sorted", "min", "max", "bool", "any", "all", "set", "isinstance",
               "callable"}

# --- methods of literals --------------------------------------------------------

STR_METHODS = ["capitalize", "casefold", "center", "count", "encode", "endswith",
               "expandtabs", "find", "format", "index", "isalnum", "isalpha", "isascii",
               "isdecimal", "isdigit", "isidentifier", "islower", "isnumeric",
               "isprintable", "isspace", "istitle", "isupper", "join", "ljust", "lower",
               "lstrip", "partition", "removeprefix", "removesuffix", "replace", "rfind",
               "rindex", "rjust", "rpartition", "rsplit", "rstrip", "split", "splitlines",
               "startswith", "strip", "swapcase", "title", "upper", "zfill"]
BYTES_METHODS = ["decode", "hex", "upper", "lower", "strip", "split", "startswith",
                 "endswith", "count", "find", "replace", "join", "isdigit", "isalpha"]
NUM_METHODS = {int: ["bit_length", "bit_count"], float: ["is_integer", "hex"]}
for _m in STR_METHODS:
    technique(f"fold.str.{_m}", 1, "method folding", f'evaluate `"...".{_m}(...)` on literals')
for _m in BYTES_METHODS:
    technique(f"fold.bytes.{_m}", 1, "method folding", f'evaluate `b"...".{_m}(...)` on literals')
for _t, _ms in NUM_METHODS.items():
    for _m in _ms:
        technique(f"fold.{_t.__name__}.{_m}", 1, "method folding",
                  f"evaluate `<{_t.__name__} literal>.{_m}()`")

# --- math --------------------------------------------------------------------------

MATH_FUNCS = ["acos", "acosh", "asin", "asinh", "atan", "atan2", "atanh", "cbrt", "ceil",
              "comb", "copysign", "cos", "cosh", "degrees", "dist", "erf", "erfc", "exp",
              "exp2", "expm1", "fabs", "factorial", "floor", "fmod", "frexp", "fsum", "gamma",
              "gcd", "hypot", "isclose", "isfinite", "isinf", "isnan", "isqrt", "lcm", "ldexp",
              "lgamma", "log", "log10", "log1p", "log2", "modf", "nextafter", "perm", "pow",
              "prod", "radians", "remainder", "sin", "sinh", "sqrt", "tan", "tanh", "trunc",
              "ulp"]
MATH_FUNCS = [f for f in MATH_FUNCS if hasattr(math, f)]
for _f in MATH_FUNCS:
    technique(f"fold.math.{_f}", 1, "math folding", f"evaluate `math.{_f}(...)` on literals")
# Arguments above these make the function slow or the result huge.
_MATH_ARG_LIMITS = {"factorial": 500, "comb": 2000, "perm": 2000, "ldexp": 2000,
                    "isqrt": 1 << 1024, "lcm": 1 << 256, "gcd": 1 << 1024}

# --- module constants ------------------------------------------------------------------

MODULE_CONSTANTS = {
    "math.pi": math.pi, "math.e": math.e, "math.tau": math.tau, "math.inf": math.inf,
    **{f"string.{n}": getattr(string, n) for n in (
        "ascii_letters", "ascii_lowercase", "ascii_uppercase", "digits", "hexdigits",
        "octdigits", "punctuation", "whitespace", "printable")},
    "sys.platform": sys.platform, "sys.maxsize": sys.maxsize, "sys.byteorder": sys.byteorder,
    "sys.hexversion": sys.hexversion, "sys.implementation.name": sys.implementation.name,
    "sys.version_info.major": sys.version_info.major,
    "sys.version_info.minor": sys.version_info.minor,
    "os.name": os.name, "os.sep": os.sep, "os.linesep": os.linesep, "os.pathsep": os.pathsep,
    "os.curdir": os.curdir, "os.pardir": os.pardir, "os.extsep": os.extsep,
    "os.altsep": os.altsep, "typing.TYPE_CHECKING": False,
}
for _q in MODULE_CONSTANTS:
    technique(f"inline.{_q}", 1, "module constants", f"replace `{_q}` with its value")
T_VERSION_INFO = technique("inline.sys.version_info", 1, "module constants",
                           "`sys.version_info >= (3, 10)` / `sys.version_info[0]` -> literal")

_BIG_FORMAT = re.compile(r"\d{5,}")


def _format_safe(fmt, args) -> bool:
    """No absurd field widths, so formatting at compile time stays cheap."""
    if isinstance(fmt, str) and _BIG_FORMAT.search(fmt):
        return False
    return not any(isinstance(a, int) and not isinstance(a, bool) and abs(a) > MAX_ARG
                   for a in _flatten(args))


def _flatten(values):
    for v in values:
        if isinstance(v, (tuple, list)):
            yield from _flatten(v)
        else:
            yield v


class Folding(Pass):

    def _emit(self, tech, result, node):
        if not can_emit(result):
            return node
        return self.did(tech, make_node(result, node), node)

    # --- operators ---------------------------------------------------------
    def visit_BinOp(self, node):
        self.generic_visit(node)
        entry = BINOPS.get(type(node.op))
        ok_l, a = const_value(node.left)
        ok_r, b = const_value(node.right)
        if not (entry and ok_l and ok_r):
            return node
        tech = f"fold.{entry[0]}"
        if not self.on(tech) or not self._binop_safe(node.op, a, b):
            return node
        try:
            result = entry[1](a, b)
        except Exception:
            return node
        return self._emit(tech, result, node)

    @staticmethod
    def _binop_safe(op, a, b) -> bool:
        if isinstance(op, ast.Pow) and isinstance(a, int) and isinstance(b, int):
            return 0 <= b <= 512 and max(a.bit_length(), 1) * b <= 1024
        if isinstance(op, ast.Pow) and isinstance(a, (float, complex)) and isinstance(b, (int, float)):
            return abs(b) <= 1e6
        if isinstance(op, ast.LShift) and isinstance(b, int):
            return b <= 1024
        if isinstance(op, ast.Mult):
            for seq, n in ((a, b), (b, a)):
                if isinstance(seq, (str, bytes, tuple)):
                    return isinstance(n, int) and len(seq) * max(n, 0) <= 256
        if isinstance(op, ast.Mod) and isinstance(a, (str, bytes)):
            return _format_safe(a, b if isinstance(b, tuple) else (b,))
        return True

    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        ok, a = const_value(node.operand)
        if not ok:
            return node
        n, fn = UNARYOPS[type(node.op)]
        tech = f"fold.{n}"
        if not self.on(tech):
            return node
        try:
            result = fn(a)
        except Exception:
            return node
        return self._emit(tech, result, node)

    def visit_Compare(self, node):
        self.generic_visit(node)
        values = []
        for operand in [node.left, *node.comparators]:
            ok, v = const_value(operand, containers=True)
            if not ok:
                return self._version_info_compare(node)
            values.append(v)
        names = []
        for i, op in enumerate(node.ops):
            n, _ = CMPOPS[type(op)]
            if isinstance(op, (ast.Is, ast.IsNot)) and not (
                isinstance(values[i], _SINGLETONS) and isinstance(values[i + 1], _SINGLETONS)
            ):
                return node  # identity of other literals is an implementation detail
            names.append(f"fold.cmp-{n}")
        if not all(self.on(t) for t in names):
            return node
        try:
            result = all(CMPOPS[type(op)][1](values[i], values[i + 1])
                         for i, op in enumerate(node.ops))
        except Exception:
            return node
        for t in names[1:]:
            self.ctx.report.bump(t)
        return self._emit(names[0], result, node)

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        tech = T_AND if isinstance(node.op, ast.And) else T_OR
        if not self.on(tech):
            return node
        values = list(node.values)
        is_and = isinstance(node.op, ast.And)
        while len(values) > 1:
            ok, v = const_value(values[0])
            if not ok:
                break
            self.did(tech, None)
            # `C and x` -> x if C is truthy else C ; `C or x` -> C if truthy else x
            if bool(v) == is_and:
                values.pop(0)
            else:
                return values[0]
        if len(values) == 1:
            return values[0]
        node.values = values
        return node

    def after_ifexp(self, node):
        ok, v = const_value(node.test)
        if ok and self.on(T_IFEXP):
            return self.did(T_IFEXP, node.body if v else node.orelse)
        return node

    def rewrite_test(self, expr):
        if isinstance(expr, (ast.List, ast.Set, ast.Dict)) and self.on(T_TRUTH):
            parts = expr.keys + expr.values if isinstance(expr, ast.Dict) else expr.elts
            if all(isinstance(p, ast.Constant) for p in parts):
                return self.did(T_TRUTH, ast.copy_location(ast.Constant(bool(parts)), expr))
        return expr

    def visit_Subscript(self, node):
        self.generic_visit(node)
        if not isinstance(node.ctx, ast.Load):
            return node
        ok, seq = const_value(node.value)
        if not ok:
            return self._version_info_subscript(node)
        if not isinstance(seq, (str, bytes, tuple)):
            return node
        if isinstance(node.slice, ast.Slice):
            parts = []
            for p in (node.slice.lower, node.slice.upper, node.slice.step):
                if p is None:
                    parts.append(None)
                    continue
                ok, v = const_value(p)
                if not ok:
                    return node
                parts.append(v)
            tech, fn = T_SLICE, lambda: seq[slice(*parts)]
        else:
            ok, idx = const_value(node.slice)
            if not ok:
                return node
            tech, fn = T_INDEX, lambda: seq[idx]
        if not self.on(tech):
            return node
        try:
            result = fn()
        except Exception:
            return node
        return self._emit(tech, result, node)

    def visit_JoinedStr(self, node):
        self.generic_visit(node)
        # Only real f-strings with fields (a format spec is also a JoinedStr; leave it).
        if not self.on(T_FSTRING) or not any(isinstance(v, ast.FormattedValue) for v in node.values):
            return node
        for v in node.values:
            if isinstance(v, ast.FormattedValue):
                if not isinstance(v.value, ast.Constant):
                    return node
                if v.format_spec is not None and not all(
                    isinstance(p, ast.Constant) for p in v.format_spec.values
                ):
                    return node
        src = ast.unparse(node)
        if _BIG_FORMAT.search(src):
            return node
        try:
            result = eval(compile(ast.Expression(body=node), "<opticomp>", "eval"), {})
        except Exception:
            return node
        if type(result) is not str:
            return node
        return self._emit(T_FSTRING, result, node)

    # --- calls ---------------------------------------------------------------
    def visit_Call(self, node):
        self.generic_visit(node)
        if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
            return node
        func = node.func
        if isinstance(func, ast.Name) and func.id in PURE_BUILTINS and self.a.is_builtin(func):
            return self._fold_builtin(node, func.id)
        if isinstance(func, ast.Attribute):
            ok, recv = const_value(func.value)
            if ok:
                return self._fold_method(node, recv, func.attr)
        qual = self.a.qualified(func)
        if qual and qual.startswith("math.") and qual[5:] in MATH_FUNCS:
            return self._fold_math(node, qual[5:])
        return node

    def _args(self, node, containers=True):
        values = []
        for arg in node.args:
            ok, v = const_value(arg, containers=containers)
            if not ok:
                return None
            values.append(v)
        return values

    def _fold_builtin(self, node, fname):
        tech = f"fold.builtin.{fname}"
        if not self.on(tech):
            return node
        if fname == "isinstance":
            return self._fold_isinstance(node, tech)
        args = self._args(node)
        if args is None:
            return node
        if fname not in _ORDER_FREE and has_unordered_text(args):
            return node
        if fname == "bytes" and args and isinstance(args[0], int) and args[0] > 256:
            return node
        if fname == "format" and not _format_safe(args[1] if len(args) > 1 else "", args):
            return node
        if fname == "pow" and len(args) >= 2 and not self._binop_safe(ast.Pow(), args[0], args[1]):
            return node
        if fname in ("str", "repr", "ascii") and not all(is_small(a) for a in args):
            return node
        try:
            result = getattr(builtins, fname)(*args)
        except Exception:
            return node
        return self._emit(tech, result, node)

    def _fold_isinstance(self, node, tech):
        if len(node.args) != 2:
            return node
        ok, value = const_value(node.args[0])
        if not ok:
            return node
        types_node = node.args[1]
        elts = types_node.elts if isinstance(types_node, ast.Tuple) else [types_node]
        types = []
        for e in elts:
            if not (isinstance(e, ast.Name) and self.a.is_builtin(e)
                    and isinstance(getattr(builtins, e.id, None), type)):
                return node
            types.append(getattr(builtins, e.id))
        return self._emit(tech, isinstance(value, tuple(types)), node)

    def _fold_method(self, node, recv, meth):
        if type(recv) is str and meth in STR_METHODS:
            tech = f"fold.str.{meth}"
        elif type(recv) is bytes and meth in BYTES_METHODS:
            tech = f"fold.bytes.{meth}"
        elif type(recv) in NUM_METHODS and meth in NUM_METHODS[type(recv)]:
            tech = f"fold.{type(recv).__name__}.{meth}"
        else:
            return node
        if not self.on(tech):
            return node
        args = self._args(node, containers=(meth == "join"))
        if args is None or has_unordered_text(args):
            return node
        if meth in ("format",) and not _format_safe(recv, args):
            return node
        if meth in ("center", "ljust", "rjust", "zfill", "expandtabs") and any(
            isinstance(a, int) and a > (64 if meth == "expandtabs" else MAX_ARG) for a in args
        ):
            return node
        if meth == "encode" or meth == "decode":
            if any(not isinstance(a, str) for a in args):
                return node
        try:
            result = getattr(recv, meth)(*args)
        except Exception:
            return node
        return self._emit(tech, result, node)

    def _fold_math(self, node, fname):
        tech = f"fold.math.{fname}"
        if not self.on(tech):
            return node
        args = self._args(node)
        if args is None:
            return node
        limit = _MATH_ARG_LIMITS.get(fname)
        if limit is not None and any(
            isinstance(a, (int, float)) and abs(a) > limit for a in _flatten(args)
        ):
            return node
        if fname in ("prod", "fsum", "dist") and len(list(_flatten(args))) > 256:
            return node
        try:
            result = getattr(math, fname)(*args)
        except Exception:
            return node
        return self._emit(tech, result, node)

    # --- module constants -----------------------------------------------------
    def visit_Attribute(self, node):
        self.generic_visit(node)
        if not isinstance(node.ctx, ast.Load):
            return node
        qual = self.a.qualified(node)
        if qual in MODULE_CONSTANTS:
            tech = f"inline.{qual}"
            if self.on(tech):
                return self.did(tech, ast.copy_location(ast.Constant(MODULE_CONSTANTS[qual]), node))
        return node

    def visit_Name(self, node):
        # `from typing import TYPE_CHECKING`, `from os import sep` ...
        if isinstance(node.ctx, ast.Load):
            qual = self.a.qualified(node)
            if qual in MODULE_CONSTANTS:
                tech = f"inline.{qual}"
                if self.on(tech):
                    return self.did(tech, ast.copy_location(ast.Constant(MODULE_CONSTANTS[qual]), node))
        return node

    def _is_version_info(self, node):
        return self.a.qualified(node) == "sys.version_info"

    def _version_info_compare(self, node):
        """``sys.version_info >= (3, 10)`` -> True/False (we compile and run on the same Python)."""
        if not self.on(T_VERSION_INFO) or len(node.ops) != 1:
            return node
        left, right = node.left, node.comparators[0]
        if self._is_version_info(left):
            ok, other = const_value(right)
            a, b = tuple(sys.version_info), other
        elif self._is_version_info(right):
            ok, other = const_value(left)
            a, b = other, tuple(sys.version_info)
        else:
            return node
        if not ok or not isinstance(other, tuple):
            return node
        try:
            result = CMPOPS[type(node.ops[0])][1](a, b)
        except Exception:
            return node
        return self._emit(T_VERSION_INFO, bool(result), node)

    def _version_info_subscript(self, node):
        if not (self.on(T_VERSION_INFO) and self._is_version_info(node.value)):
            return node
        if isinstance(node.slice, ast.Slice):
            parts = []
            for p in (node.slice.lower, node.slice.upper, node.slice.step):
                ok, v = const_value(p) if p is not None else (True, None)
                if not ok:
                    return node
                parts.append(v)
            result = tuple(sys.version_info)[slice(*parts)]
        else:
            ok, idx = const_value(node.slice)
            if not ok or not isinstance(idx, int):
                return node
            try:
                result = tuple(sys.version_info)[idx]
            except IndexError:
                return node
        return self._emit(T_VERSION_INFO, result, node)
