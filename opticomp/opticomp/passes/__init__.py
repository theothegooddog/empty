"""The optimization pipeline."""

from __future__ import annotations

import ast
import copy
import pickle
import sys

from ..analysis import Analysis
from ..registry import Context, Report
from .aggressive import Aggressive
from .dce import DeadCode, Propagation
from .folding import Folding
from .idioms import Idioms
from .typed import Typed

PIPELINE = (Propagation, Folding, Typed, Idioms, DeadCode, Aggressive)
MAX_ROUNDS = 6


def fix_empty_blocks(tree: ast.AST) -> None:
    """Any block that became empty gets a ``pass``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Module):
            continue
        if isinstance(getattr(node, "body", None), list) and not node.body:
            node.body = [ast.copy_location(ast.Pass(), node)]
        if isinstance(node, ast.Try) and not node.handlers and not node.finalbody:
            node.finalbody = [ast.copy_location(ast.Pass(), node)]
        if isinstance(node, ast.Match):
            for case in node.cases:
                if not case.body:
                    case.body = [ast.Pass()]


def _run_pass(cls, tree, ctx):
    ctx.analysis = Analysis(tree)
    p = cls(ctx)
    tree = p.run(tree) if hasattr(p, "run") else p.visit(tree)
    fix_empty_blocks(tree)
    ast.fix_missing_locations(tree)
    return tree, p.changed


def optimize_tree(tree: ast.Module, level: int = 1, skip=(), only=None):
    """Return ``(optimized copy of tree, Report)``. ``tree`` itself is not modified."""
    tree = copy.deepcopy(tree)
    ctx = Context(level=level, skip=frozenset(skip),
                  only=frozenset(only) if only is not None else None)
    if level <= 0:
        return tree, ctx.report
    broken: set = set()
    for _ in range(MAX_ROUNDS):
        backup, counts = pickle.dumps(tree), dict(ctx.report.changes)
        changed = False
        try:  # fast path: the whole round, one check at the end
            for cls in PIPELINE:
                if cls not in broken:
                    tree, c = _run_pass(cls, tree, ctx)
                    changed |= c
            compile(tree, "<opticomp-check>", "exec", dont_inherit=True)
        except Exception:
            # Slow path: redo the round pass by pass and drop whichever pass misbehaves.
            # (A bug in a pass must never break the user's program.)
            tree, ctx.report.changes = pickle.loads(backup), counts
            changed = False
            for cls in PIPELINE:
                if cls in broken:
                    continue
                snap, snap_counts = pickle.dumps(tree), dict(ctx.report.changes)
                try:
                    tree, c = _run_pass(cls, tree, ctx)
                    compile(tree, "<opticomp-check>", "exec", dont_inherit=True)
                    changed |= c
                except Exception as exc:
                    print(f"[opticomp] internal: pass {cls.__name__} skipped ({exc!r})",
                          file=sys.stderr)
                    broken.add(cls)
                    tree, ctx.report.changes = pickle.loads(snap), snap_counts
        if not changed:
            break
    return tree, ctx.report


def optimize_source(source: str, filename: str = "<string>", level: int = 1, skip=(), only=None):
    """Parse ``source`` and return ``(optimized_tree, report)``."""
    return optimize_tree(ast.parse(source, filename=filename), level, skip, only)


__all__ = ["optimize_tree", "optimize_source", "fix_empty_blocks", "Report"]
