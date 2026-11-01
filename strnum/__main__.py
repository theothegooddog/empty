"""python -m strnum [script.py [args...] | -c CODE]

With no arguments, starts a REPL where int literals are StrInts:

    >>> (5)
    '5'
"""

import code
import os
import sys

from .transform import _ReplCompiler, exec_strnum, install


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    install()

    if not argv:
        from .core import senumerate, slen, srange

        namespace = {"__name__": "__main__", "range": srange, "len": slen, "enumerate": senumerate}
        console = code.InteractiveConsole(namespace)
        console.compile = _ReplCompiler()
        console.interact(banner="strnum REPL: every int is a str. Ctrl-D to exit.", exitmsg="")
        return 0

    if argv[0] == "-c":
        if len(argv) < 2:
            print("usage: python -m strnum -c CODE", file=sys.stderr)
            return 2
        sys.argv = ["-c", *argv[2:]]
        exec_strnum(argv[1], filename="<string>")
        return 0

    path = argv[0]
    with open(path, encoding="utf-8") as f:
        source = f.read()
    sys.argv = argv
    sys.path.insert(0, os.path.dirname(os.path.abspath(path)))
    exec_strnum(source, {"__name__": "__main__", "__file__": path}, filename=path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
