import ast
import os
import subprocess
import sys
import textwrap

import pytest

from opticomp import optimize_source


def opt(src, level=1):
    tree, report = optimize_source(textwrap.dedent(src), level=level)
    return ast.unparse(tree), report


def run_both(src, level=1):
    """Exec original and optimized code; their printed output must match."""
    src = textwrap.dedent(src)
    outs = []
    for code in (src, opt(src, level)[0]):
        lines = []
        ns = {"print": lambda *a: lines.append(a)}
        try:
            exec(compile(code, "<t>", "exec"), ns)
        except Exception as e:
            lines.append(("raised", type(e).__name__))
        outs.append(lines)
    assert outs[0] == outs[1]
    return outs[0]


# --- what gets optimized -------------------------------------------------

def test_folding_and_propagation():
    out, rep = opt("""
        TIMEOUT = 60 * 60
        x = TIMEOUT * 2 + len("abcd")
    """)
    assert "x = 7204" in out and rep


def test_dead_branch_removed():
    out, _ = opt("""
        DEBUG = False
        if DEBUG:
            print("debug")
        else:
            print("prod")
    """)
    assert "debug" not in out and "print('prod')" in out


def test_unreachable_after_return():
    out, _ = opt("""
        def f():
            return 1
            print("never")
    """)
    assert "never" not in out


def test_level2_hoisting_and_power():
    out, _ = opt("""
        def f(n):
            out = []
            for i in range(n):
                out.append(i ** 2)
            return out
    """, level=2)
    assert "_oc_out_append" in out and "i * i" in out
    run_both("def f(n):\n out=[]\n for i in range(n):\n  out.append(i**2)\n return out\nprint(f(5))", 2)


# --- what must NOT be changed --------------------------------------------

def test_rebound_constant_not_propagated():
    out, _ = opt("""
        LIMIT = 5
        def bump():
            global LIMIT
            LIMIT += 1
        bump()
        print(LIMIT)
    """)
    assert "print(LIMIT)" in out


def test_lowercase_name_not_propagated():
    out, _ = opt("limit = 5\nprint(limit)")
    assert "print(limit)" in out


def test_shadowed_builtin_not_folded():
    out, _ = opt("def len(x): return 99\nprint(len('ab'))")
    assert "len('ab')" in out


def test_generator_keeps_dead_yield():
    run_both("""
        def g():
            return
            yield 1
        print(list(g()), type(g()).__name__)
    """)


def test_dead_assignment_in_function_kept():
    # Removing `x = 1` would change UnboundLocalError into a global lookup.
    run_both("""
        x = "global"
        def f():
            if False:
                x = 1
            return x
        print(f())
    """)


def test_runtime_errors_preserved():
    run_both("print(1 / 0)")
    run_both("print(len(5))")


def test_hoisting_skips_rebound_object():
    out, _ = opt("""
        def f():
            out = []
            for i in range(3):
                out.append(i)
                out = list(out)
            return out
    """, level=2)
    assert "_oc_" not in out


def test_hoisting_skips_conditional_only_calls():
    out, _ = opt("""
        def f(xs, out=None):
            for x in xs:
                if out is not None:
                    out.append(x)
    """, level=2)
    assert "_oc_" not in out


# --- the import hijack ---------------------------------------------------

def run_script(tmp_path, body, **env):
    script = tmp_path / "script.py"
    script.write_text(textwrap.dedent(body))
    before = script.read_text()
    e = {**os.environ, "OPTICOMP_CACHE_DIR": str(tmp_path / "cache"), **env}
    p = subprocess.run([sys.executable, str(script), "a1"], capture_output=True, text=True, env=e)
    assert script.read_text() == before  # source never modified
    return p


SCRIPT = """
    import opticomp
    import sys
    FLAG = False
    print("ran", __name__, sys.argv[1:], "optimized" if getattr(sys.modules["__main__"], "__opticomp__", False) else "original")
    if FLAG:
        print("dead")
"""


def test_runs_optimized_copy_exactly_once(tmp_path):
    p = run_script(tmp_path, SCRIPT)
    assert p.returncode == 0, p.stderr
    assert p.stdout.splitlines() == ["ran __main__ ['a1'] optimized"]


def test_disable(tmp_path):
    p = run_script(tmp_path, SCRIPT, OPTICOMP_DISABLE="1")
    assert p.stdout.splitlines() == ["ran __main__ ['a1'] original"]


def test_cache_hit(tmp_path):
    run_script(tmp_path, SCRIPT)
    p = run_script(tmp_path, SCRIPT, OPTICOMP_VERBOSE="1")
    assert "[cached]" in p.stderr


def test_exit_code_and_traceback(tmp_path):
    p = run_script(tmp_path, "import opticomp\nimport sys\nsys.exit(3)\n")
    assert p.returncode == 3
    p = run_script(tmp_path, "import opticomp\n\ndef f():\n    raise ValueError('boom')\nf()\n")
    assert p.returncode == 1
    assert "ValueError: boom" in p.stderr and 'script.py", line 4' in p.stderr
    assert "_runner.py" not in p.stderr


def test_warns_when_code_precedes_import(tmp_path):
    p = run_script(tmp_path, "print('early')\nimport opticomp\n")
    assert "warning" in p.stderr
