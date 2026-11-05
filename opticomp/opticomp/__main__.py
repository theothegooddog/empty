"""Command line: ``python -m opticomp [--level N] [--show] script.py [args...]``."""

from __future__ import annotations

import argparse
import ast
import sys

from ._runner import _name_set, read_source, run_path
from .passes import optimize_source
from .registry import TECHNIQUES


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m opticomp",
        description="Run (or show) an optimized copy of a Python script. "
                    "The script file is never modified.",
    )
    parser.add_argument("--level", type=int, default=None,
                        help="0 = off, 1 = safe passes (default), 2 = aggressive")
    parser.add_argument("--show", action="store_true",
                        help="print the optimized source and a change report instead of running")
    parser.add_argument("--list", action="store_true", help="list every optimization technique")
    parser.add_argument("script", nargs="?")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    ns = parser.parse_args(argv)

    if ns.list:
        by_cat = {}
        for t in TECHNIQUES.values():
            by_cat.setdefault(t.category, []).append(t)
        for cat, techs in by_cat.items():
            print(f"\n{cat} ({len(techs)})")
            for t in techs:
                print(f"  [L{t.level}] {t.name:42s} {t.description}")
        print(f"\n{len(TECHNIQUES)} techniques "
              f"({sum(t.level == 1 for t in TECHNIQUES.values())} at level 1, "
              f"{sum(t.level == 2 for t in TECHNIQUES.values())} at level 2)")
        return
    if not ns.script:
        parser.error("a script is required")

    if ns.show:
        level = 1 if ns.level is None else ns.level
        tree, report = optimize_source(read_source(ns.script), ns.script, level,
                                       skip=_name_set("OPTICOMP_SKIP") or (),
                                       only=_name_set("OPTICOMP_ONLY"))
        print(ast.unparse(tree))
        print(f"\n# opticomp level {level}: {report.summary()}", file=sys.stderr)
        return

    sys.argv = [ns.script, *ns.args]
    run_path(ns.script, level=ns.level)


if __name__ == "__main__":
    main()
