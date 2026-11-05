"""Every technique fires on its sample and never changes program output."""

import contextlib
import io
import os

import pytest

os.environ.setdefault("OPTICOMP_DISABLE", "1")  # importing opticomp here must not hijack pytest

from opticomp import TECHNIQUES, optimize_source  # noqa: E402
import ast  # noqa: E402

from samples import build  # noqa: E402

SAMPLES = build()


def run(code):
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "<sample>", "exec"), {"__name__": "__main__"})
    except Exception as e:  # the same exception must happen in both versions
        return buf.getvalue() + f"<raised {type(e).__name__}: {e}>"
    return buf.getvalue()


def test_every_technique_has_a_sample():
    missing = sorted(set(TECHNIQUES) - set(SAMPLES))
    assert not missing, f"techniques without a sample: {missing}"
    unknown = sorted(set(SAMPLES) - set(TECHNIQUES))
    assert not unknown, f"samples for unknown techniques: {unknown}"


@pytest.mark.parametrize("tech", sorted(SAMPLES))
def test_technique_fires_and_preserves_output(tech):
    level, src = SAMPLES[tech]
    tree, report = optimize_source(src, level=level)
    assert tech in report.changes, f"{tech} did not fire; report: {report.summary()}"
    optimized = ast.unparse(tree)
    assert run(src) == run(optimized), optimized


@pytest.mark.parametrize("tech", sorted(t for t in SAMPLES if TECHNIQUES[t].level == 2))
def test_level2_techniques_off_by_default(tech):
    _, src = SAMPLES[tech]
    _, report = optimize_source(src, level=1)
    assert tech not in report.changes


def test_skip_and_only():
    src = "print(1 + 2)"
    _, rep = optimize_source(src, skip={"fold.add"})
    assert "fold.add" not in rep.changes
    _, rep = optimize_source("print(1 + 2, 'a'.upper())", only={"fold.str.upper"})
    assert set(rep.changes) == {"fold.str.upper"}
