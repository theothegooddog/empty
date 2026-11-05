# opticomp

Put one line at the top of a script:

```python
import opticomp
```

When you run the script, `opticomp` reads its source, applies optimizations to an
in-memory copy, runs that copy as `__main__`, and exits with its exit code. The
original, unoptimized version never runs, and **the file on disk is never changed**.

```
pip install -e .
python examples/demo.py
OPTICOMP_VERBOSE=1 python examples/demo.py      # show what was optimized
python -m opticomp --show examples/demo.py      # print the optimized source
```

## Optimizations

**Level 1 (default).** These keep the program's behavior the same:

| Pass | Example |
|---|---|
| Constant propagation | `DEBUG = False` … `if DEBUG:` → `if False:` (only `UPPER_CASE` names assigned once at module level and never rebound) |
| Constant folding | `24 * 60 * 60` → `86400`, `len("abc")` → `3`, `x if True else y` → `x` |
| Dead-code elimination | drops `if False:` / `while 0:` branches and code after `return`/`raise`/`break`/`continue` |

**Level 2 (`OPTICOMP_LEVEL=2`).** Faster, but relies on assumptions:

| Pass | Example | Assumption |
|---|---|---|
| Method hoisting | `out.append(x)` in a loop → `append = out.append` before the loop | the object exists and has the method even if the loop runs zero times |
| Strength reduction | `x ** 2` → `x * x` | `x` is a number where the two are the same (for very large floats, `**` raises `OverflowError` but `*` gives `inf`) |

Safety guards: no folding or propagation when the file uses `exec`, `eval`, `globals()`,
`setattr`, `import *`, or rebinds the builtin. Dead code that contains `yield`, `global`,
`nonlocal`, or `super`, or a dead local assignment inside a function, is kept.
Line numbers are preserved, so tracebacks still point at the right lines of your file.

## Configuration

| Variable | Effect |
|---|---|
| `OPTICOMP_LEVEL=0/1/2` | which passes to apply (default 1) |
| `OPTICOMP_VERBOSE=1` | print a summary of changes to stderr |
| `OPTICOMP_DISABLE=1` | run the original script untouched |
| `OPTICOMP_CACHE=0` | don't cache optimized bytecode (default cache: `~/.cache/opticomp`) |
| `OPTICOMP_CACHE_DIR` | change the cache location |

## Notes and limits

- `import opticomp` must be the **first statement** (after the docstring, `__future__`
  and other imports). Code above it has already run once, un-optimized; opticomp prints
  a warning when it sees that.
- Only the script you run directly is optimized. If a library imports `opticomp`, or a
  multiprocessing child process re-imports your script, it does nothing.
- These are source-level optimizations. CPython already folds some constants itself, so
  how much faster your script gets depends on the code. On `examples/demo.py` with
  Python 3.13: original 0.43s, level 1 0.37s, level 2 0.32s.
