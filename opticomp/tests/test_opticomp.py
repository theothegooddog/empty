import ast
import os
import subprocess
import sys
import textwrap

import pytest

os.environ.setdefault("OPTICOMP_DISABLE", "1")
from opticomp import optimize_source  # noqa: E402


def opt(src, level=1):
    tree, report = optimize_source(textwrap.dedent(src), level=level)
    return ast.unparse(tree), report


def run_both(src, level=2):
    """Exec original and optimized code; their printed output must match."""
    src = textwrap.dedent(src)
    outs = []
    for code in (src, opt(src, level)[0]):
        lines = []
        ns = {"print": lambda *a: lines.append(a), "__name__": "__main__"}
        try:
            exec(compile(code, "<t>", "exec"), ns)
        except Exception as e:
            lines.append(("raised", type(e).__name__, str(e)))
        outs.append(lines)
    assert outs[0] == outs[1], opt(src, level)[0]
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


# --- the import hijack ---------------------------------------------------

def run_script(tmp_path, body, **env):
    script = tmp_path / "script.py"
    script.write_text(textwrap.dedent(body))
    before = script.read_text()
    e = {k: v for k, v in os.environ.items() if not k.startswith("OPTICOMP_")}
    e.update({"OPTICOMP_CACHE_DIR": str(tmp_path / "cache"), **env})
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


# --- type-aware rules must only fire on proven exact types -----------------

def test_bool_is_not_treated_as_int():
    assert run_both("b = True\nprint(b + 0, b * 1, +b)") == [(1, 1, 1)]


def test_unknown_parameter_types_untouched():
    out, _ = opt("def f(x):\n    return x + 0, x * 1, x ** 1\n")
    assert "x + 0" in out and "x * 1" in out
    run_both("""
        class Weird:
            def __add__(self, o): return "added"
            def __mul__(self, o): return "multiplied"
        def f(x):
            return x + 0, x * 1
        print(f(Weird()))
    """, level=1)


def test_str_subclass_from_str_call_not_assumed_exact():
    run_both("""
        class S(str):
            def __add__(self, o): return "custom"
        class A:
            def __str__(self): return S("q")
        def f():
            s = str(A())
            return s + ""
        print(f())
    """, level=1)


def test_variable_rebound_to_other_type_is_unknown():
    run_both("""
        def f(flag):
            n = 0
            if flag:
                n = "text"
            return n * 1
        print(f(True), f(False))
    """)


def test_nonlocal_rebinding_defeats_inference():
    run_both("""
        def f():
            n = 1
            def g():
                nonlocal n
                n = [1]
            g()
            return n * 1, n + n
        print(f())
    """)


def test_global_rebinding_defeats_module_constant():
    run_both("""
        LIMIT = 5
        def bump():
            global LIMIT
            LIMIT = LIMIT + 1
        bump()
        print(LIMIT)
    """)


def test_eval_disables_name_based_rewrites():
    out, rep = opt("X = 2\nprint(eval('X') + X)\n")
    assert "prop.module-constant" not in rep.changes


def test_string_sets_not_folded_into_order_dependent_results():
    out, _ = opt("print(list({'a', 'b', 'c'}), str({'a', 'b'}))")
    assert "list(" in out and "str(" in out
    out, rep = opt("print(len({'a', 'b'}), sorted({'b', 'a'}))")
    assert "fold.builtin.len" in rep.changes and "fold.builtin.sorted" in rep.changes


def test_huge_results_not_folded():
    out, _ = opt("x = 'a' * 10**6\ny = 2 ** 100000\nz = '{:>99999}'.format(1)\n")
    assert "10 ** 6" in out or "1000000" in out
    assert "2 ** 100000" in out and "99999" in out


def test_runtime_errors_still_raise():
    for src in ("print(1 / 0)", "print(int('x'))", "print(math.sqrt(-1))", "print('abc'[5])"):
        run_both("import math\n" + src)


def test_format_with_explicit_indexes_not_converted():
    out, _ = opt("a, b = 1, 2\nprint('{1}{0}'.format(a, b), '{x}'.format(x=a))")
    assert ".format(" in out


def test_mangled_getattr_untouched():
    out, _ = opt("class A:\n    def f(self):\n        return getattr(self, '__x')\n")
    assert "getattr" in out


def test_custom_eq_none_kept_at_level_1():
    run_both("""
        class AlwaysEq:
            def __eq__(self, o): return True
        print(AlwaysEq() == None)
    """, level=1)


def test_type_checking_block_removed():
    out, rep = opt("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import json\nprint(1)")
    assert "import json" not in out and "dce.if-constant" in rep.changes


def test_version_check_resolved():
    out, _ = opt("import sys\nif sys.version_info >= (3, 0):\n    print('new')\nelse:\n    print('old')")
    assert "old" not in out


def test_comprehension_variable_does_not_leak_type():
    run_both("""
        n = "s"
        xs = [n * 2 for n in range(3)]
        print(xs, n * 1)
    """)


def test_class_attribute_not_propagated():
    run_both("""
        class C:
            X = 1
            def get(self): return self.X
        C.X = 5
        print(C().get())
    """)


def test_local_constant_not_used_before_assignment():
    run_both("""
        def f(flag):
            if flag:
                try:
                    return k
                except UnboundLocalError:
                    return "unbound"
            k = 3
            return k
        print(f(True), f(False))
    """)


def test_while_true_with_break_keeps_following_code():
    run_both("""
        def f():
            while True:
                break
            return "after"
        print(f())
    """)


def test_isinstance_merge_needs_builtin_types():
    out, _ = opt("class int2: pass\nx = 1\nprint(isinstance(x, int) or isinstance(x, int2))")
    assert out.count("isinstance") == 2
