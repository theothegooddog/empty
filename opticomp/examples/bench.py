"""Time small programs before and after optimization: python examples/bench.py"""

import os
import textwrap
import timeit

os.environ.setdefault("OPTICOMP_DISABLE", "1")
from opticomp import optimize_source  # noqa: E402

CASES = {
    "identity comprehension": "def f(xs):\n    return [x for x in xs]",
    "list(generator)": "def f(xs):\n    return list(x * 2 for x in xs)",
    "join(generator)": "def f(xs):\n    return ','.join(str(x) for x in xs)",
    "len(x) == 0 check": """
        def f(xs):
            hits = 0
            for i in range(len(xs)):
                buf = [0] * (i % 3)
                if len(buf) == 0:
                    hits += 1
            return hits""",
    "int membership": """
        def f(xs):
            t = 0
            for n in range(len(xs)):
                if n % 7 in (1, 2, 3, 5, 8, 13):
                    t += 1
            return t""",
    "feature flag + constants": """
        DEBUG = False
        SCALE = 2 ** 10
        def f(xs):
            t = 0
            for x in xs:
                if DEBUG:
                    print(x)
                t += x * SCALE // 1024
            return t""",
    "str.format": "def f(xs):\n    return ['{} = {}'.format(x, x) for x in xs]",
    "math.sqrt in loop (L2)": """
        import math
        def f(xs):
            t = 0.0
            for x in xs:
                t += math.sqrt(x)
            return t""",
    "x ** 2 (L2)": "def f(xs):\n    return sum([x ** 2 for x in xs])",
}

xs = list(range(2000))
print(f"{'case':26s} {'original':>10s} {'optimized':>10s} {'speedup':>8s}")
for name, src in CASES.items():
    src = textwrap.dedent(src)
    level = 2 if "(L2)" in name else 1
    tree, report = optimize_source(src, level=level)
    times = []
    for code in (compile(src, "<orig>", "exec"), compile(tree, "<opt>", "exec")):
        ns = {}
        exec(code, ns)
        f = ns["f"]
        times.append(min(timeit.repeat(lambda: f(xs), number=200, repeat=5)))
    print(f"{name:26s} {times[0]*5000:8.0f}us {times[1]*5000:8.0f}us {times[0]/times[1]:7.2f}x")
