"""Command line: ``python -m opticomp [--level N] [--show] script.py [args...]``."""

from __future__ import annotations

import argparse
import ast
import sys

from ._runner import read_source, run_path
from .optimizer import optimize_source


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
    parser.add_argument("script")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    ns = parser.parse_args(argv)

    if ns.show:
        level = 1 if ns.level is None else ns.level
        tree, report = optimize_source(read_source(ns.script), ns.script, level)
        print(ast.unparse(tree))
        print(f"\n# opticomp level {level}: {report.summary()}", file=sys.stderr)
        return

    sys.argv = [ns.script, *ns.args]
    run_path(ns.script, level=ns.level)


if __name__ == "__main__":
    main()
