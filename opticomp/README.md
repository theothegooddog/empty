# opticomp

Put one line at the top of a script:

```python
import opticomp
```

When you run the script, `opticomp` reads its source, applies **331 optimization
techniques** to an in-memory copy, runs that copy as `__main__`, and exits with its exit
code. The original, unoptimized version never runs, and **the file on disk is never
changed**.

```
pip install -e .
python examples/demo.py
OPTICOMP_VERBOSE=1 python examples/demo.py      # print what was optimized
python -m opticomp --show examples/demo.py      # print the optimized source
python -m opticomp --list                       # list all 331 techniques
python examples/bench.py                        # before/after timings
```

## Techniques

| Category | Count | Examples |
|---|---:|---|
| Constant folding | 33 | `24 * 60 * 60` → `86400`, `"abc"[1]` → `"b"`, `f"{1}-{2}"` → `"1-2"`, `if []:` → `if False:` |
| Builtin folding | 30 | `len("abc")` → `3`, `sorted((3, 1, 2))` → `[1, 2, 3]`, `isinstance(3, int)` → `True` |
| Method folding | 62 | every pure `str` method (`"a,b".split(",")`, `"x".upper()` …), 14 `bytes` methods, `int`/`float` methods |
| Math folding | 55 | `math.sqrt(2.0)`, `math.factorial(10)`, `math.log(8, 2)` … on literal arguments |
| Module constants | 30 | `math.pi`, `string.digits`, `sys.platform`, `os.sep`, `typing.TYPE_CHECKING`, `sys.version_info >= (3, 10)` |
| Constant propagation | 2 | `DEBUG = False` … `if DEBUG:` → `if False:`; same for function locals assigned once |
| Dead code | 13 | drops `if False:` branches, code after `return`/`raise`/`break`/`continue`/an endless loop, `assert True`, `try: pass` handlers |
| Idioms | 50 | `[x for x in y]` → `list(y)`, `list(x for …)` → `[x for …]`, `'{} {}'.format(a, b)` → `f'{a} {b}'`, `not (a in b)` → `a not in b`, `range(0, n)` → `range(n)` |
| Type-aware | 46 | when a variable is **proven** to be an exact `int` / `float` / `str` / `bool` / container: `n + 0` → `n`, `n ** 2` → `n * n`, `n in (1, 2, 3)` → `n in {1, 2, 3}`, `len(c) == 0` → `not c`, `b == True` → `b` |
| **Aggressive (level 2)** | 10 | `math.sqrt` looked up once per loop, `x ** 2` → `x * x` for any `x`, `for k in d.keys()` → `for k in d`, `x == None` → `x is None` |

Rewrites at level 1 (the default) don't change what your program does. Level 2 is opt-in with
`OPTICOMP_LEVEL=2`. Each level 2 technique states its assumption in `--list`. For example,
`x == None` → `x is None` assumes `x` doesn't override `==`.

## How it stays safe

- **Name resolution.** A builtin is folded only when its name is never rebound anywhere in the
  file. If the file uses `exec`, `eval`, `globals()`, `locals()`, `vars()` or `import *`,
  nothing name-based is touched.
- **Type inference.** A variable has a type only if *every* assignment to it produces that
  exact type. Function arguments, tuple unpacking, `with … as`, and values from `str()`
  (which can return a subclass) count as unknown. `bool` is never treated as `int`, because
  `True + 0` is `1`.
- **Guarded evaluation.** Nothing that would build a huge value is computed at compile time
  (`'a' * 10**6`, `2 ** 100000`, `'{:>99999}'`). Expressions that raise (`1 / 0`,
  `int('x')`) are left alone, so they still raise at runtime. Sets of strings aren't folded
  into anything order-dependent, because their order changes between runs.
- **Dead code** that contains `yield`, `global`, `nonlocal`, `super`, or (inside a function)
  any assignment is kept, because removing it could change scoping or turn a generator into a
  function.
- **A bug can't break your program.** Every round of passes must produce code that compiles. If
  a pass fails, it is rolled back and skipped. If optimization fails entirely, the original
  code runs.
- Line numbers are preserved, so tracebacks point at the right lines of your file.

### Testing

- `tests/test_techniques.py` runs every one of the 331 techniques on its own sample program. Each
  technique must fire, and the program must print exactly the same output before and after. A
  separate test fails if any registered technique has no sample.
- `tests/test_opticomp.py` covers tricky cases where a rewrite must *not* happen, plus the
  import hijack itself (runs once, exit codes, tracebacks, caching, source never modified).
- Stress test: optimizing the whole Python standard library produces code that compiles. The
  doctests of 36 stdlib modules give identical results on the optimized versions (610 rewrites
  applied, including all 469 `_pydecimal` doctests).

## Speed

The gains come from the idiom, type-aware and dead-code techniques. Plain constant folding
mostly repeats work CPython's compiler already does for simple cases, but it lets
propagation and dead-code elimination combine. From `examples/bench.py` on Python 3.13:

| Case | Speedup |
|---|---:|
| `[x for x in xs]` → `list(xs)` | 5.7x |
| `list(x * 2 for x in xs)` → list comprehension | 1.7x |
| `n in (1, 2, 3, 5, 8, 13)` for a known int → set lookup | 1.4x |
| `x ** 2` → `x * x` | 1.3x |
| `','.join(generator)` → `join(list)` | 1.2x |
| `'{} = {}'.format(x, x)` → f-string | 1.2x |
| `DEBUG` flag + constants folded away | 1.2x |
| `math.sqrt` hoisted out of a loop (level 2) | 1.1x |

How much faster *your* script gets depends on how much of its time is spent in code these
patterns cover.

Some well-known techniques are deliberately **not** included, because measurements showed they
don't help on Python 3.11+: caching `obj.append` in a local before a loop (0.7x, slower,
because the interpreter already specializes method calls), copying builtins into locals,
`[f(x) for …]` → `map`, and `x / 2.0` → `x * 0.5`.

## Configuration

| Variable | Effect |
|---|---|
| `OPTICOMP_LEVEL=0/1/2` | 0 = off, 1 = safe techniques (default), 2 = also aggressive ones |
| `OPTICOMP_VERBOSE=1` | print which techniques fired to stderr |
| `OPTICOMP_DISABLE=1` | run the original script untouched |
| `OPTICOMP_SKIP=a,b` | turn off individual techniques (names from `--list`) |
| `OPTICOMP_ONLY=a,b` | use only these techniques |
| `OPTICOMP_CACHE=0` | don't cache optimized bytecode (default cache: `~/.cache/opticomp`) |
| `OPTICOMP_CACHE_DIR` | change the cache location |

## Notes and limits

- `import opticomp` must be the **first statement** (after the docstring, `__future__`
  and other imports). Code above it has already run once, unoptimized, and opticomp prints a
  warning when it sees that.
- Only the script you run directly is optimized. If a library imports `opticomp`, or a
  multiprocessing child process re-imports your script, it does nothing.
- Folding `sys.platform`, `os.sep`, `sys.version_info` and similar assumes the program runs on
  the same interpreter that optimized it. That's always true here, and the cache is keyed by
  Python version. It also assumes those values aren't monkeypatched at runtime, for example
  by tests that mock `sys.platform`.
- Requires Python 3.10+.
