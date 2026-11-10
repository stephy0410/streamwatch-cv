"""Política de confianza de dos umbrales y tres zonas.

- ``s >= upper``          → ``accepted`` (aceptada por la política; no implica acierto)
- ``lower <= s < upper``  → ``doubt`` (zona de duda: caso para revisar)
- ``s < lower``           → ``low`` (baja confianza)

La unidad de análisis es la **detección candidata** (salida del detector por encima del piso
``conf_floor`` y de una clase monitoreada). El *estado del frame* resume sus detecciones:
toma la zona de su mejor detección, o ``no_detections`` / ``error``, que nunca se convierten
en una confianza artificial de cero.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from streamwatch.config import ConfidenceConfig

ZONES = ("accepted", "doubt", "low")
FRAME_STATES = (*ZONES, "no_detections", "error")


@dataclass(frozen=True)
class ConfidencePolicy:
    lower: float
    upper: float

    @classmethod
    def from_config(cls, cfg: ConfidenceConfig) -> ConfidencePolicy:
        return cls(cfg.lower, cfg.upper)

    def __post_init__(self) -> None:
        if not 0 <= self.lower < self.upper <= 1:
            raise ValueError("Se requiere 0 <= lower < upper <= 1")

    def zone(self, score: float) -> str:
        if score >= self.upper:
            return "accepted"
        if score >= self.lower:
            return "doubt"
        return "low"

    def summarize(self, scores: list[float]) -> FrameSummary:
        counts = {z: 0 for z in ZONES}
        for s in scores:
            counts[self.zone(s)] += 1
        if not scores:
            return FrameSummary(counts, None, None, "no_detections")
        best = max(scores)
        return FrameSummary(counts, best, sum(scores) / len(scores), self.zone(best))


@dataclass(frozen=True)
class FrameSummary:
    zone_counts: dict[str, int] = field(default_factory=dict)
    max_score: float | None = None
    mean_score: float | None = None
    frame_state: str = "no_detections"
