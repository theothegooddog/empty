"""Hijack the importing script: run an optimized copy, never the original."""

from __future__ import annotations

import ast
import hashlib
import marshal
import os
import sys
import tokenize
import types

from .optimizer import optimize_tree

VERSION = "0.1.0"
_THIS_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _log(msg: str) -> None:
    if _env_flag("OPTICOMP_VERBOSE"):
        print(f"[opticomp] {msg}", file=sys.stderr)


def _level() -> int:
    try:
        return int(os.environ.get("OPTICOMP_LEVEL", "1"))
    except ValueError:
        return 1


# ---------------------------------------------------------------------------
# compile (with an on-disk cache of the optimized bytecode)
# ---------------------------------------------------------------------------

def _cache_dir() -> str:
    if os.environ.get("OPTICOMP_CACHE_DIR"):
        return os.environ["OPTICOMP_CACHE_DIR"]
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "opticomp")


def compile_optimized(source: str, filename: str, level: int):
    """Return ``(code_object, report_summary, from_cache)``."""
    use_cache = os.environ.get("OPTICOMP_CACHE", "1") != "0"
    key = hashlib.sha256(
        "\0".join([VERSION, sys.version, str(level), filename, source]).encode()
    ).hexdigest()
    path = os.path.join(_cache_dir(), key + ".bin")

    if use_cache:
        try:
            with open(path, "rb") as fh:
                summary, code = marshal.load(fh)
            return code, summary, True
        except (OSError, EOFError, ValueError, TypeError):
            pass

    tree = ast.parse(source, filename=filename)
    tree, report = optimize_tree(tree, level)
    code = compile(tree, filename, "exec", dont_inherit=True)
    summary = report.summary()

    if use_cache:
        try:
            os.makedirs(_cache_dir(), exist_ok=True)
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "wb") as fh:
                marshal.dump((summary, code), fh)
            os.replace(tmp, path)
        except OSError:
            pass
    return code, summary, False


def read_source(path: str) -> str:
    with tokenize.open(path) as fh:  # honours PEP 263 encoding cookies
        return fh.read()


# ---------------------------------------------------------------------------
# running
# ---------------------------------------------------------------------------

def run_path(path: str, level: int | None = None, base_module=None):
    """Run the optimized version of the script at *path* as ``__main__``.

    Never returns: exits the interpreter with the script's exit status.
    """
    level = _level() if level is None else level
    path = os.path.abspath(path)
    source = read_source(path)
    code, summary, cached = compile_optimized(source, path, level)
    _log(f"{os.path.basename(path)} (level {level}): {summary}"
         + (" [cached]" if cached else ""))

    module = types.ModuleType("__main__")
    if base_module is not None:
        for attr in ("__spec__", "__loader__", "__package__", "__cached__"):
            if hasattr(base_module, attr):
                setattr(module, attr, getattr(base_module, attr))
    module.__file__ = path
    module.__builtins__ = __builtins__
    module.__opticomp__ = True
    sys.modules["__main__"] = module

    try:
        exec(code, module.__dict__)
    except SystemExit:
        raise
    except BaseException as exc:  # report like the interpreter would ...
        tb = exc.__traceback__.tb_next if exc.__traceback__ else None  # ... minus our frame
        exc.__traceback__ = tb
        sys.excepthook(type(exc), exc, tb)
        raise SystemExit(130 if isinstance(exc, KeyboardInterrupt) else 1) from None
    raise SystemExit(0)


def _find_importer():
    """The frame that executed ``import opticomp`` (skipping importlib)."""
    frame = sys._getframe(1)
    while frame is not None:
        fname = frame.f_code.co_filename
        if fname.startswith("<frozen importlib") or os.path.dirname(
            os.path.abspath(fname)
        ) == _THIS_PACKAGE_DIR:
            frame = frame.f_back
            continue
        return frame
    return None


def _warn_if_code_ran_before(source: str, filename: str, import_line: int) -> None:
    """Anything executed before ``import opticomp`` has already run once."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return
    for i, stmt in enumerate(tree.body):
        if stmt.lineno >= import_line:
            return
        is_docstring = i == 0 and isinstance(stmt, ast.Expr) and isinstance(
            getattr(stmt, "value", None), ast.Constant
        ) and isinstance(stmt.value.value, str)
        if is_docstring or isinstance(stmt, (ast.Import, ast.ImportFrom)):
            continue
        print(
            f"[opticomp] warning: {os.path.basename(filename)} line {stmt.lineno} runs "
            f"before 'import opticomp', so it executed un-optimized too. "
            f"Put 'import opticomp' at the top of the file.",
            file=sys.stderr,
        )
        return


def bootstrap() -> None:
    if _env_flag("OPTICOMP_DISABLE"):
        return
    main = sys.modules.get("__main__")
    if main is None or getattr(main, "__opticomp__", False):
        return  # already running the optimized copy
    frame = _find_importer()
    if (
        frame is None
        or frame.f_globals is not main.__dict__
        or frame.f_globals.get("__name__") != "__main__"
        or frame.f_code.co_name != "<module>"
    ):
        return  # imported by a library, a REPL, multiprocessing child, etc.
    path = main.__dict__.get("__file__")
    if not path or not path.endswith(".py") or not os.path.isfile(path):
        return  # `python -c`, stdin, frozen apps ...

    source = read_source(path)
    _warn_if_code_ran_before(source, path, frame.f_lineno)
    del frame
    run_path(path, base_module=main)
