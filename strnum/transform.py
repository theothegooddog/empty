"""Rewrite Python source so every int literal becomes a StrInt.

``x = (5)`` is compiled as ``x = StrInt("5")``.
"""

from __future__ import annotations

import ast
import builtins
import codeop
import importlib.abc
import importlib.machinery
import importlib.util
import sys

from .core import StrInt

__all__ = ["transform", "compile_strnum", "exec_strnum", "install", "uninstall"]

# Name the rewritten code calls. It lives in builtins so every module sees it.
_NAME = "__strnum_StrInt__"
MARKER = b"# strnum"


class _IntLiterals(ast.NodeTransformer):
    def visit_Constant(self, node: ast.Constant):
        if type(node.value) is int:  # not bool, float or complex
            call = ast.Call(
                func=ast.Name(id=_NAME, ctx=ast.Load()),
                args=[ast.Constant(value=str(node.value))],
                keywords=[],
            )
            return ast.copy_location(call, node)
        return node

    # match/case patterns must stay literal constants.
    def visit_MatchValue(self, node):
        return node

    def visit_MatchSingleton(self, node):
        return node


# Builtins that return ints, swapped for StrInt versions at the top of each
# rewritten module. A later `def range(...)` in the module still wins.
_SHADOWED = {"range": "srange", "len": "slen", "enumerate": "senumerate"}


def _prelude() -> list[ast.stmt]:
    names = [ast.alias(name=src, asname=dst) for dst, src in _SHADOWED.items()]
    return [ast.ImportFrom(module="strnum.core", names=names, level=0)]


def _insert_at(body: list[ast.stmt]) -> int:
    """Index after the docstring and any `from __future__` imports."""
    i = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        i = 1
    while i < len(body) and isinstance(body[i], ast.ImportFrom) and body[i].module == "__future__":
        i += 1
    return i


def transform(source: str, filename: str = "<strnum>", mode: str = "exec") -> ast.AST:
    """Parse source and return an AST with int literals replaced."""
    tree = ast.parse(source, filename, mode)
    tree = _IntLiterals().visit(tree)
    if mode == "exec":
        at = _insert_at(tree.body)
        tree.body[at:at] = _prelude()
    return ast.fix_missing_locations(tree)


def compile_strnum(source: str, filename: str = "<strnum>", mode: str = "exec"):
    _ensure_builtin()
    return compile(transform(source, filename, mode), filename, mode, dont_inherit=True)


def exec_strnum(source: str, globals_: dict | None = None, filename: str = "<strnum>"):
    """Run source with int literals as StrInt. Returns the globals dict."""
    g = {"__name__": "__main__"} if globals_ is None else globals_
    exec(compile_strnum(source, filename), g)
    return g


def _ensure_builtin():
    setattr(builtins, _NAME, StrInt)


# --------------------------------------------------------------------------
# Import hook: modules whose first two lines contain "# strnum" are rewritten.
# --------------------------------------------------------------------------

class _Loader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        # Compile from source every time so rewritten code is never written
        # to __pycache__, where a normal import could pick it up.
        source = importlib.util.decode_source(self.get_data(self.path))
        return compile_strnum(source, self.path)


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or not isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            return None
        try:
            with open(spec.origin, "rb") as f:
                head = f.readline() + f.readline()
        except OSError:
            return None
        if MARKER not in head:
            return None
        spec.loader = _Loader(fullname, spec.origin)
        return spec


_finder = _Finder()


def install():
    """Rewrite any module imported from now on that starts with '# strnum'."""
    _ensure_builtin()
    if _finder not in sys.meta_path:
        sys.meta_path.insert(0, _finder)


def uninstall():
    if _finder in sys.meta_path:
        sys.meta_path.remove(_finder)


# --------------------------------------------------------------------------
# REPL support.
# --------------------------------------------------------------------------

class _ReplCompiler:
    """Drop-in for codeop.CommandCompiler that rewrites int literals."""

    def __call__(self, source, filename="<input>", symbol="single"):
        if codeop.compile_command(source, filename, symbol) is None:
            return None  # incomplete input: ask for more lines
        return compile_strnum(source, filename, symbol)
