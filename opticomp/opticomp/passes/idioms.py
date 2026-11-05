"""Rewrite common idioms into faster equivalents with identical behaviour.

Each rewrite only fires when the builtin involved really is the builtin
(not shadowed anywhere in the file).
"""

from __future__ import annotations

import ast
import keyword
import string

from ..registry import technique
from .base import Pass, call, name, simple_call

T_NOT_IS = technique("idiom.not-is", 1, "idioms", "`not (a is b)` -> `a is not b`")
T_NOT_IS_NOT = technique("idiom.not-is-not", 1, "idioms", "`not (a is not b)` -> `a is b`")
T_NOT_IN = technique("idiom.not-in", 1, "idioms", "`not (a in b)` -> `a not in b`")
T_NOT_NOT_IN = technique("idiom.not-not-in", 1, "idioms", "`not (a not in b)` -> `a in b`")
T_NOT_NOT = technique("idiom.not-not-test", 1, "idioms", "`if not not x:` -> `if x:`")
T_BOOL_TEST = technique("idiom.bool-call-test", 1, "idioms", "`if bool(x):` -> `if x:`")
T_ISINST_TUPLE = technique("idiom.isinstance-single-tuple", 1, "idioms",
                           "`isinstance(x, (int,))` -> `isinstance(x, int)`")
T_ISINST_MERGE = technique("idiom.isinstance-merge", 1, "idioms",
                           "`isinstance(x, int) or isinstance(x, str)` -> `isinstance(x, (int, str))`")
T_CHAIN = technique("idiom.compare-chain", 1, "idioms", "`a < b and b < c` -> `a < b < c`")
T_RET_BOOL = technique("idiom.if-return-bool", 1, "idioms",
                       "`if c: return True / return False` -> `return bool(c)`")
T_RET_NOT = technique("idiom.if-return-not", 1, "idioms",
                      "`if c: return False / return True` -> `return not c`")

# (`list()`, `str()`, `int()` ... are already handled by builtin folding.)
_EMPTY = {"dict": lambda: ast.Dict(keys=[], values=[])}
T_EMPTY = {n: technique(f"idiom.empty-{n}-call", 1, "idioms", f"`{n}()` -> literal")
           for n in _EMPTY}
T_DICT_KW = technique("idiom.dict-kwargs-literal", 1, "idioms", "`dict(a=1, b=2)` -> `{'a': 1, 'b': 2}`")
T_LIST_LIT = technique("idiom.list-literal-call", 1, "idioms", "`list([a, b])` / `list((a, b))` -> `[a, b]`")
T_TUPLE_LIT = technique("idiom.tuple-literal-call", 1, "idioms", "`tuple([a, b])` -> `(a, b)`")
T_SET_LIT = technique("idiom.set-literal-call", 1, "idioms", "`set([a, b])` -> `{a, b}`")
T_DICT_LIT = technique("idiom.dict-literal-call", 1, "idioms", "`dict({...})` -> `{...}`")
T_LIST_GEN = technique("idiom.list-genexpr", 1, "idioms", "`list(x for x in y)` -> `[x for x in y]`")
T_SET_GEN = technique("idiom.set-genexpr", 1, "idioms", "`set(x for x in y)` -> `{x for x in y}`")
T_DICT_GEN = technique("idiom.dict-genexpr", 1, "idioms",
                       "`dict((k, v) for ...)` -> `{k: v for ...}`")
T_LIST_ID = technique("idiom.list-identity-comprehension", 1, "idioms", "`[x for x in y]` -> `list(y)`")
T_SET_ID = technique("idiom.set-identity-comprehension", 1, "idioms", "`{x for x in y}` -> `set(y)`")

# outer(inner(x)) -> outer(x)  (or -> inner(x) when marked "inner")
_REDUNDANT = {
    ("list", "list"): "outer", ("list", "tuple"): "outer", ("tuple", "list"): "outer",
    ("set", "list"): "outer", ("set", "tuple"): "outer",
    ("set", "set"): "outer", ("frozenset", "list"): "outer", ("frozenset", "tuple"): "outer",
    ("sorted", "list"): "outer", ("sorted", "tuple"): "outer", ("sorted", "sorted"): "outer",
    ("list", "sorted"): "inner", ("sum", "list"): "outer", ("sum", "tuple"): "outer",
    ("min", "list"): "outer", ("max", "list"): "outer",
}
T_REDUNDANT = {k: technique(f"idiom.{k[0]}-of-{k[1]}", 1, "idioms",
                            f"`{k[0]}({k[1]}(x))` -> `{k[0] if v == 'outer' else k[1]}(x)`")
               for k, v in _REDUNDANT.items()}
T_RANGE_ZERO = technique("idiom.range-zero-start", 1, "idioms", "`range(0, n)` -> `range(n)`")
T_RANGE_STEP = technique("idiom.range-unit-step", 1, "idioms", "`range(a, b, 1)` -> `range(a, b)`")
T_ENUM_ZERO = technique("idiom.enumerate-zero-start", 1, "idioms", "`enumerate(x, 0)` -> `enumerate(x)`")
T_SORTED_REV = technique("idiom.sorted-reverse-false", 1, "idioms",
                         "`sorted(x, reverse=False)` -> `sorted(x)`")
T_GETATTR = technique("idiom.getattr-constant", 1, "idioms", "`getattr(o, 'name')` -> `o.name`")
T_JOIN_GEN = technique("idiom.join-genexpr", 1, "idioms",
                       "`','.join(x for ...)` -> `','.join([x for ...])` (join builds a list anyway)")
T_TUPLE_GEN = technique("idiom.tuple-genexpr", 1, "idioms", "`tuple(x for ...)` -> `tuple([x for ...])`")
T_SORTED_GEN = technique("idiom.sorted-genexpr", 1, "idioms", "`sorted(x for ...)` -> `sorted([x for ...])`")
T_FORMAT = technique("idiom.format-to-fstring", 1, "idioms", "`'{} {}'.format(a, b)` -> `f'{a} {b}'`")
T_FSTR_CONV = {
    "str": technique("idiom.fstring-str-call", 1, "idioms", "`f'{str(x)}'` -> `f'{x!s}'`"),
    "repr": technique("idiom.fstring-repr-call", 1, "idioms", "`f'{repr(x)}'` -> `f'{x!r}'`"),
    "ascii": technique("idiom.fstring-ascii-call", 1, "idioms", "`f'{ascii(x)}'` -> `f'{x!a}'`"),
}


def _is_builtin_type_name(a, node) -> bool:
    import builtins
    return (isinstance(node, ast.Name) and a.is_builtin(node)
            and isinstance(getattr(builtins, node.id, None), type))


def _same_name(x, y) -> bool:
    return isinstance(x, ast.Name) and isinstance(y, ast.Name) and x.id == y.id


class Idioms(Pass):

    # --- not / tests -------------------------------------------------------
    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, ast.Not) and isinstance(node.operand, ast.Compare) \
                and len(node.operand.ops) == 1:
            cmp = node.operand
            flip = {ast.Is: (ast.IsNot, T_NOT_IS), ast.IsNot: (ast.Is, T_NOT_IS_NOT),
                    ast.In: (ast.NotIn, T_NOT_IN), ast.NotIn: (ast.In, T_NOT_NOT_IN)}
            entry = flip.get(type(cmp.ops[0]))
            if entry and self.on(entry[1]):
                cmp.ops = [entry[0]()]
                return self.did(entry[1], cmp)
        return node

    def rewrite_test(self, expr):
        if (isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not)
                and isinstance(expr.operand, ast.UnaryOp) and isinstance(expr.operand.op, ast.Not)
                and self.on(T_NOT_NOT)):
            return self.did(T_NOT_NOT, expr.operand.operand)
        if simple_call(expr, "bool", self.a, 1) and self.on(T_BOOL_TEST):
            return self.did(T_BOOL_TEST, expr.args[0])
        return expr

    # --- boolean operators -------------------------------------------------
    def visit_BoolOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, ast.Or) and self.on(T_ISINST_MERGE):
            node.values = self._merge_isinstance(node.values)
        if isinstance(node.op, ast.And) and self.on(T_CHAIN):
            node.values = self._merge_chains(node.values)
        return node.values[0] if len(node.values) == 1 else node

    def _isinstance_parts(self, v):
        if not (simple_call(v, "isinstance", self.a, 2) and isinstance(v.args[0], ast.Name)):
            return None
        t = v.args[1]
        types = t.elts if isinstance(t, ast.Tuple) else [t]
        if not types or not all(_is_builtin_type_name(self.a, x) for x in types):
            return None
        return v.args[0], types

    def _merge_isinstance(self, values):
        out = []
        for v in values:
            parts = self._isinstance_parts(v)
            prev = self._isinstance_parts(out[-1]) if out else None
            if parts and prev and _same_name(parts[0], prev[0]):
                merged = ast.Tuple(elts=prev[1] + parts[1], ctx=ast.Load())
                out[-1].args[1] = ast.copy_location(merged, out[-1])
                self.did(T_ISINST_MERGE, None)
            else:
                out.append(v)
        return out

    def _merge_chains(self, values):
        out = []
        for v in values:
            prev = out[-1] if out else None
            if (isinstance(prev, ast.Compare) and isinstance(v, ast.Compare)
                    and len(v.ops) == 1
                    and isinstance(v.left, (ast.Name, ast.Constant))
                    and ast.dump(prev.comparators[-1]) == ast.dump(v.left)):
                prev.ops.append(v.ops[0])
                prev.comparators.append(v.comparators[0])
                self.did(T_CHAIN, None)
            else:
                out.append(v)
        return out

    # --- statements --------------------------------------------------------
    def generic_visit(self, node):
        super().generic_visit(node)
        for fname in ("body", "orelse", "finalbody"):
            block = getattr(node, fname, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                setattr(node, fname, self._if_return(block))
        return node

    @staticmethod
    def _ret_const(stmts):
        if len(stmts) == 1 and isinstance(stmts[0], ast.Return) \
                and isinstance(stmts[0].value, ast.Constant) and isinstance(stmts[0].value.value, bool):
            return stmts[0].value.value
        return None

    def _if_return(self, block):
        out = []
        i = 0
        while i < len(block):
            s = block[i]
            if isinstance(s, ast.If):
                then = self._ret_const(s.body)
                if s.orelse:
                    other, consumed = self._ret_const(s.orelse), 1
                elif i + 1 < len(block):
                    other, consumed = self._ret_const(block[i + 1:i + 2]), 2
                else:
                    other = None
                if then is not None and other is not None and then != other:
                    new = self._bool_return(s.test, negate=not then, like=s)
                    if new is not None:
                        out.append(new)
                        i += consumed
                        continue
            out.append(s)
            i += 1
        return out

    def _bool_return(self, test, negate, like):
        if negate:
            if not self.on(T_RET_NOT):
                return None
            value = ast.UnaryOp(op=ast.Not(), operand=test)
            self.did(T_RET_NOT, None)
        else:
            if not self.on(T_RET_BOOL):
                return None
            if self.a.type_of(test) == "bool" or (
                isinstance(test, ast.Compare)
                and all(isinstance(o, (ast.In, ast.NotIn, ast.Is, ast.IsNot)) for o in test.ops)
            ):
                value = test
            elif self.builtin_free("bool"):
                value = call(name("bool", test), [test], test)
            else:
                return None
            self.did(T_RET_BOOL, None)
        return ast.copy_location(ast.Return(value=value), like)

    # --- calls -----------------------------------------------------------------
    def visit_Call(self, node):
        self.generic_visit(node)
        f = node.func
        if isinstance(f, ast.Attribute):
            return self._method_call(node)
        if not (isinstance(f, ast.Name) and self.a.is_builtin(f)):
            return node
        n = f.id
        if any(isinstance(a, ast.Starred) for a in node.args) or any(
            k.arg is None for k in node.keywords
        ):
            return node
        args, kws = node.args, node.keywords

        if not args and not kws and n in _EMPTY and self.on(T_EMPTY[n]):
            return self.did(T_EMPTY[n], ast.copy_location(_EMPTY[n](), node))
        if n == "dict" and not args and kws and self.on(T_DICT_KW):
            return self.did(T_DICT_KW, ast.copy_location(ast.Dict(
                keys=[ast.Constant(k.arg) for k in kws], values=[k.value for k in kws]), node))
        if kws and n not in ("sorted", "min", "max", "enumerate"):
            return node

        if len(args) == 1 and not kws:
            arg = args[0]
            if n == "list" and isinstance(arg, (ast.List, ast.Tuple)) and self.on(T_LIST_LIT):
                return self.did(T_LIST_LIT, ast.copy_location(ast.List(elts=arg.elts, ctx=ast.Load()), node))
            if n == "list" and isinstance(arg, ast.ListComp) and self.on(T_LIST_LIT):
                return self.did(T_LIST_LIT, arg)
            if n == "tuple" and isinstance(arg, (ast.List, ast.Tuple)) and self.on(T_TUPLE_LIT):
                return self.did(T_TUPLE_LIT, ast.copy_location(ast.Tuple(elts=arg.elts, ctx=ast.Load()), node))
            if n == "set" and isinstance(arg, (ast.List, ast.Tuple, ast.Set)) and arg.elts \
                    and self.on(T_SET_LIT):
                return self.did(T_SET_LIT, ast.copy_location(ast.Set(elts=arg.elts), node))
            if n == "set" and isinstance(arg, ast.SetComp) and self.on(T_SET_LIT):
                return self.did(T_SET_LIT, arg)
            if n == "dict" and isinstance(arg, (ast.Dict, ast.DictComp)) and self.on(T_DICT_LIT):
                return self.did(T_DICT_LIT, arg)
            if isinstance(arg, ast.GeneratorExp):
                if n == "list" and self.on(T_LIST_GEN):
                    return self.did(T_LIST_GEN, ast.copy_location(
                        ast.ListComp(elt=arg.elt, generators=arg.generators), node))
                if n == "set" and self.on(T_SET_GEN):
                    return self.did(T_SET_GEN, ast.copy_location(
                        ast.SetComp(elt=arg.elt, generators=arg.generators), node))
                if (n == "dict" and isinstance(arg.elt, ast.Tuple) and len(arg.elt.elts) == 2
                        and not any(isinstance(e, ast.Starred) for e in arg.elt.elts)
                        and self.on(T_DICT_GEN)):
                    k, v = arg.elt.elts
                    return self.did(T_DICT_GEN, ast.copy_location(
                        ast.DictComp(key=k, value=v, generators=arg.generators), node))
                if n == "tuple" and self.on(T_TUPLE_GEN):
                    node.args = [ast.copy_location(
                        ast.ListComp(elt=arg.elt, generators=arg.generators), arg)]
                    return self.did(T_TUPLE_GEN, node)
        if n == "sorted" and len(args) == 1 and isinstance(args[0], ast.GeneratorExp) \
                and self.on(T_SORTED_GEN):
            g = args[0]
            node.args = [ast.copy_location(ast.ListComp(elt=g.elt, generators=g.generators), g)]
            return self.did(T_SORTED_GEN, node)

        # outer(inner(x))
        if args and isinstance(args[0], ast.Call) and isinstance(args[0].func, ast.Name):
            inner = args[0]
            key = (n, inner.func.id)
            if (key in _REDUNDANT and self.on(T_REDUNDANT[key])
                    and self.a.is_builtin(inner.func) and len(inner.args) == 1
                    and not any(isinstance(a, ast.Starred) for a in inner.args)
                    and (not inner.keywords or key == ("list", "sorted"))
                    and (len(args) == 1 or n == "sum")
                    and (not kws or n in ("sorted", "min", "max"))
                    and not (key == ("sorted", "sorted") and kws)):
                self.did(T_REDUNDANT[key], None)
                if _REDUNDANT[key] == "inner":
                    return inner
                node.args = [inner.args[0], *args[1:]]
                return node

        if n == "range" and not kws:
            if (len(args) == 2 and isinstance(args[0], ast.Constant) and args[0].value == 0
                    and type(args[0].value) is int and self.on(T_RANGE_ZERO)):
                node.args = [args[1]]
                return self.did(T_RANGE_ZERO, node)
            if (len(args) == 3 and isinstance(args[2], ast.Constant) and args[2].value == 1
                    and type(args[2].value) is int and self.on(T_RANGE_STEP)):
                node.args = args[:2]
                return self.did(T_RANGE_STEP, node)
        if n == "enumerate" and self.on(T_ENUM_ZERO):
            start = None
            if len(args) == 2 and not kws:
                start = args[1]
            elif len(args) == 1 and len(kws) == 1 and kws[0].arg == "start":
                start = kws[0].value
            if (isinstance(start, ast.Constant) and type(start.value) is int and start.value == 0):
                node.args, node.keywords = args[:1], []
                return self.did(T_ENUM_ZERO, node)
        if n == "sorted" and self.on(T_SORTED_REV):
            rev = [k for k in kws if k.arg == "reverse"]
            if rev and isinstance(rev[0].value, ast.Constant) and rev[0].value.value is False:
                node.keywords = [k for k in kws if k.arg != "reverse"]
                return self.did(T_SORTED_REV, node)
        if n == "getattr" and len(args) == 2 and not kws and self.on(T_GETATTR):
            attr = args[1]
            if (isinstance(attr, ast.Constant) and isinstance(attr.value, str)
                    and attr.value.isidentifier() and not keyword.iskeyword(attr.value)
                    and attr.value.isascii()
                    and not (attr.value.startswith("__") and not attr.value.endswith("__"))):
                return self.did(T_GETATTR, ast.copy_location(
                    ast.Attribute(value=args[0], attr=attr.value, ctx=ast.Load()), node))
        if n == "isinstance" and len(args) == 2 and not kws and self.on(T_ISINST_TUPLE):
            t = args[1]
            if isinstance(t, ast.Tuple) and len(t.elts) == 1 and not isinstance(t.elts[0], ast.Starred):
                node.args = [args[0], t.elts[0]]
                return self.did(T_ISINST_TUPLE, node)
        return node

    def _method_call(self, node):
        f = node.func
        if not (isinstance(f.value, ast.Constant) and isinstance(f.value.value, str)):
            return node
        if (f.attr == "join" and len(node.args) == 1 and not node.keywords
                and isinstance(node.args[0], ast.GeneratorExp) and self.on(T_JOIN_GEN)):
            g = node.args[0]
            node.args = [ast.copy_location(ast.ListComp(elt=g.elt, generators=g.generators), g)]
            return self.did(T_JOIN_GEN, node)
        if f.attr == "format" and self.on(T_FORMAT):
            return self._format_to_fstring(node)
        return node

    def _format_to_fstring(self, node):
        if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
            return node
        try:
            parsed = list(string.Formatter().parse(node.func.value.value))
        except ValueError:
            return node
        values, args = [], list(node.args)
        fields = 0
        for literal, field, spec, conv in parsed:
            if literal:
                values.append(ast.Constant(literal))
            if field is None:
                continue
            if field != "" or (spec and "{" in spec) or fields >= len(args):
                return node
            fv = ast.FormattedValue(
                value=args[fields], conversion=ord(conv) if conv else -1,
                format_spec=ast.JoinedStr(values=[ast.Constant(spec)]) if spec else None)
            values.append(fv)
            fields += 1
        if fields == 0 or fields != len(args):
            return node
        return self.did(T_FORMAT, ast.copy_location(ast.JoinedStr(values=values), node))

    def visit_FormattedValue(self, node):
        self.generic_visit(node)
        v = node.value
        if node.conversion == -1 and isinstance(v, ast.Call) and isinstance(v.func, ast.Name) \
                and v.func.id in T_FSTR_CONV and simple_call(v, v.func.id, self.a, 1):
            tech = T_FSTR_CONV[v.func.id]
            if self.on(tech):
                node.value = v.args[0]
                node.conversion = ord({"str": "s", "repr": "r", "ascii": "a"}[v.func.id])
                return self.did(tech, node)
        return node

    # [x for x in y] -> list(y)
    def _identity_comp(self, node, tech, ctor):
        if (len(node.generators) == 1 and not node.generators[0].ifs
                and not node.generators[0].is_async
                and isinstance(node.generators[0].target, ast.Name)
                and isinstance(node.elt, ast.Name)
                and node.elt.id == node.generators[0].target.id
                and self.builtin_free(ctor) and self.on(tech)):
            return self.did(tech, call(name(ctor, node), [node.generators[0].iter], node))
        return node

    def visit_ListComp(self, node):
        self.generic_visit(node)
        return self._identity_comp(node, T_LIST_ID, "list")

    def visit_SetComp(self, node):
        self.generic_visit(node)
        return self._identity_comp(node, T_SET_ID, "set")
