"""Public entry points (kept for backwards compatibility)."""

from .passes import optimize_source, optimize_tree  # noqa: F401
from .registry import TECHNIQUES, Report  # noqa: F401
