"""opticomp - optimize a script on the fly.

Put ``import opticomp`` at the top of a script. When the script is run, the
import reads the script's source, applies AST optimizations to an in-memory
copy, runs that copy as ``__main__`` and then exits, so the original
un-optimized module body never runs. The file on disk is never modified.

Environment variables:

    OPTICOMP_LEVEL=0|1|2   0 = no passes, 1 = safe passes (default),
                           2 = also aggressive passes
    OPTICOMP_VERBOSE=1     print what was optimized to stderr
    OPTICOMP_DISABLE=1     run the original script untouched
    OPTICOMP_CACHE=0       don't cache optimized bytecode
    OPTICOMP_CACHE_DIR=..  cache location (default ~/.cache/opticomp)
"""

from ._runner import VERSION as __version__
from ._runner import bootstrap as _bootstrap
from ._runner import run_path
from .optimizer import Report, optimize_source, optimize_tree

__all__ = ["optimize_source", "optimize_tree", "run_path", "Report", "__version__"]

_bootstrap()
