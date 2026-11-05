"""The catalogue of optimization techniques and the per-run context.

Every rewrite opticomp performs belongs to exactly one named technique.
Techniques can be listed (``python -m opticomp --list``), counted in the
report, and switched off individually (``OPTICOMP_SKIP=name,name``).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Technique:
    name: str
    level: int          # 1 = safe (default), 2 = aggressive (opt-in)
    category: str
    description: str


TECHNIQUES: dict[str, Technique] = {}


def technique(name: str, level: int, category: str, description: str) -> str:
    if name in TECHNIQUES:
        raise ValueError(f"duplicate technique {name!r}")
    TECHNIQUES[name] = Technique(name, level, category, description)
    return name


@dataclass
class Report:
    """How many times each technique fired."""

    changes: dict[str, int] = field(default_factory=dict)

    def bump(self, what: str, n: int = 1) -> None:
        self.changes[what] = self.changes.get(what, 0) + n

    def __bool__(self) -> bool:
        return bool(self.changes)

    def total(self) -> int:
        return sum(self.changes.values())

    def summary(self) -> str:
        if not self.changes:
            return "no changes"
        parts = ", ".join(f"{k} x{v}" for k, v in sorted(self.changes.items()))
        return f"{self.total()} rewrites using {len(self.changes)} techniques ({parts})"


@dataclass
class Context:
    level: int = 1
    skip: frozenset = frozenset()
    only: frozenset | None = None
    report: Report = field(default_factory=Report)
    analysis: object = None   # analysis.Analysis, rebuilt before every pass

    def enabled(self, name: str) -> bool:
        tech = TECHNIQUES[name]
        if tech.level > self.level or name in self.skip:
            return False
        if self.only is not None and name not in self.only:
            return False
        return True
