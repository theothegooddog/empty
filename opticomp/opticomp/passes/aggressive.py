"""Level 2: faster, but each rewrite relies on an assumption about your code.

The assumption is stated in each technique's description and in the README.
Enable with ``OPTICOMP_LEVEL=2``.
"""

from __future__ import annotations

import ast

from ..registry import technique
from .base import FUNC_NODES, Pass, simple_call

T_HOIST = technique("aggr.module-attr-hoisting", 2, "aggressive",
                    "look up `math.sqrt` etc. once before a loop instead of every iteration "
                    "(assumes the module attribute isn't reassigned during the loop)")
T_POW2 = technique("aggr.pow-two", 2, "aggressive",
                   "`x ** 2` -> `x * x` for any name (assumes a numeric type; for huge floats "
                   "`**` raises OverflowError where `*` gives inf)")
T_POW3 = technique("aggr.pow-three", 2, "aggressive", "`x ** 3` -> `x * x * x` (same assumption)")
T_KEYS_ITER = technique("aggr.dict-keys-iteration", 2, "aggressive",
                        "`for k in d.keys():` -> `for k in d:` (assumes d is a mapping)")
T_KEYS_IN = technique("aggr.dict-keys-membership", 2, "aggressive",
                      "`k in d.keys()` -> `k in d` (assumes d is a mapping)")
T_LEN_TEST = technique("aggr.len-test", 2, "aggressive",
                       "`if len(x):` -> `if x:` for any x (assumes truthiness matches length; "
                       "not true for e.g. numpy arrays)")
T_LEN_ZERO = technique("aggr.len-eq-zero", 2, "aggressive",
                       "`len(x) == 0` -> `not x` for any x (same assumption)")
T_TYPE_IS = technique("aggr.type-is", 2, "aggressive",
                      "`type(x) == T` -> `type(x) is T` (assumes no metaclass overrides `==`)")
T_EQ_NONE = technique("aggr.eq-none", 2, "aggressive",
                      "`x == None` -> `x is None` (assumes x doesn't override `==`)")
T_NE_NONE = technique("aggr.ne-none", 2, "aggressive",
                      "`x != None` -> `x is not None` (assumes x doesn't override `!=`)")


def _is_keys_call(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "keys" and not node.args and not node.keywords)


def _square(x, n, like):
    out = x
    for _ in range(n - 1):
        out = ast.BinOp(left=out, op=ast.Mult(), right=ast.Name(id=x.id, ctx=ast.Load()))
    return ast.copy_location(out, like)


class Aggressive(Pass):

    def visit_BinOp(self, node):
        self.generic_visit(node)
        if (isinstance(node.op, ast.Pow) and isinstance(node.left, ast.Name)
                and isinstance(node.right, ast.Constant) and type(node.right.value) is int):
            if node.right.value == 2 and self.on(T_POW2):
                return self.did(T_POW2, _square(node.left, 2, node))
            if node.right.value == 3 and self.on(T_POW3):
                return self.did(T_POW3, _square(node.left, 3, node))
        return node

    def visit_For(self, node):
        self.generic_visit(node)
        if _is_keys_call(node.iter) and self.on(T_KEYS_ITER):
            node.iter = node.iter.func.value
            self.did(T_KEYS_ITER, None)
        return node

    def visit_comprehension(self, node):
        node = super().visit_comprehension(node)
        if _is_keys_call(node.iter) and self.on(T_KEYS_ITER):
            node.iter = node.iter.func.value
            self.did(T_KEYS_ITER, None)
        return node

    def visit_Compare(self, node):
        self.generic_visit(node)
        if len(node.ops) != 1:
            return node
        op, l, r = node.ops[0], node.left, node.comparators[0]
        if isinstance(op, (ast.In, ast.NotIn)) and _is_keys_call(r) and self.on(T_KEYS_IN):
            node.comparators = [r.func.value]
            return self.did(T_KEYS_IN, node)
        if (isinstance(op, ast.Eq) and simple_call(l, "len", self.a, 1)
                and isinstance(r, ast.Constant) and type(r.value) is int and r.value == 0
                and self.on(T_LEN_ZERO)):
            return self.did(T_LEN_ZERO, ast.copy_location(
                ast.UnaryOp(op=ast.Not(), operand=l.args[0]), node))
        if (isinstance(op, (ast.Eq, ast.NotEq)) and simple_call(l, "type", self.a, 1)
                and isinstance(r, (ast.Name, ast.Attribute)) and self.on(T_TYPE_IS)):
            node.ops = [ast.Is() if isinstance(op, ast.Eq) else ast.IsNot()]
            return self.did(T_TYPE_IS, node)
        if isinstance(r, ast.Constant) and r.value is None:
            if isinstance(op, ast.Eq) and self.on(T_EQ_NONE):
                node.ops = [ast.Is()]
                return self.did(T_EQ_NONE, node)
            if isinstance(op, ast.NotEq) and self.on(T_NE_NONE):
                node.ops = [ast.IsNot()]
                return self.did(T_NE_NONE, node)
        return node

    def visit_UnaryOp(self, node):
        # `not len(x)` (what `len(x) == 0` becomes at level 1) -> `not x`
        self.generic_visit(node)
        if (isinstance(node.op, ast.Not) and simple_call(node.operand, "len", self.a, 1)
                and self.on(T_LEN_ZERO)):
            node.operand = node.operand.args[0]
            return self.did(T_LEN_ZERO, node)
        return node

    def rewrite_test(self, expr):
        if simple_call(expr, "len", self.a, 1) and self.on(T_LEN_TEST):
            return self.did(T_LEN_TEST, expr.args[0])
        return expr

    # --- module attribute hoisting -------------------------------------------
    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        if self.on(T_HOIST):
            node.body = self._hoist_block(node.body)
        return node

    visit_AsyncFunctionDef = visit_FunctionDef

    def _hoist_block(self, stmts):
        out = []
        for s in stmts:
            if isinstance(s, (ast.For, ast.While)):
                out.extend(self._hoist_loop(s))
                continue
            for fname in ("body", "orelse", "finalbody"):
                block = getattr(s, fname, None)
                if (isinstance(block, list) and block and isinstance(block[0], ast.stmt)
                        and not isinstance(s, (*FUNC_NODES, ast.ClassDef))):
                    setattr(s, fname, self._hoist_block(block))
            for h in getattr(s, "handlers", None) or []:
                h.body = self._hoist_block(h.body)
            out.append(s)
        return out

    def _hoist_loop(self, loop):
        found: dict[tuple[str, str], str] = {}
        a = self.a

        def scan(n):
            if isinstance(n, (*FUNC_NODES, ast.ClassDef)):
                return
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and isinstance(n.func.value, ast.Name) and a.module_of(n.func.value):
                key = (n.func.value.id, n.func.attr)
                if key not in found:
                    alias = f"_oc_{key[0]}_{key[1]}"
                    if alias not in a.all_bound_names:
                        found[key] = alias
            for c in ast.iter_child_nodes(n):
                scan(c)

        for s in loop.body + loop.orelse:
            scan(s)
        if isinstance(loop, ast.While):
            scan(loop.test)
        if not found:
            return [loop]

        def rewrite(n):
            if isinstance(n, (*FUNC_NODES, ast.ClassDef)):
                return
            for fname, child in ast.iter_fields(n):
                items = child if isinstance(child, list) else [child]
                for c in items:
                    if isinstance(c, ast.AST):
                        rewrite(c)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and isinstance(n.func.value, ast.Name):
                alias = found.get((n.func.value.id, n.func.attr))
                if alias:
                    n.func = ast.copy_location(ast.Name(id=alias, ctx=ast.Load()), n.func)

        rewrite(loop)
        pre = []
        for (mod, attr), alias in found.items():
            pre.append(ast.copy_location(ast.Assign(
                targets=[ast.Name(id=alias, ctx=ast.Store())],
                value=ast.Attribute(value=ast.Name(id=mod, ctx=ast.Load()), attr=attr,
                                    ctx=ast.Load())), loop))
            self.did(T_HOIST, None)
        return pre + [loop]
