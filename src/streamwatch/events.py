"""Contrato del evento de inferencia (versión 1). Ver ``docs/CONTRATO.md``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1"


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def event_id(run_id: str, source_id: str, seq: int) -> str:
    return f"evt-{run_id}-{source_id}-{seq:06d}"


def frame_id(source_id: str, read_index: int) -> str:
    return f"{source_id}-{read_index:07d}"


class DetectionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    class_id: int
    class_name: str
    score: float = Field(..., ge=0, le=1)
    zone: Literal["accepted", "doubt", "low"]
    box: list[float] = Field(..., min_length=4, max_length=4)


class InferenceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"] = SCHEMA_VERSION
    event_id: str
    run_id: str
    frame_id: str
    seq: int = Field(..., ge=1, description="n-ésimo frame procesado de la fuente en la corrida")
    source_id: str
    timestamp: str = Field(..., description="Momento del registro (UTC, ISO-8601)")
    captured_at: str = Field(..., description="Momento en que se decodificó el frame (UTC)")
    task: Literal["detection"] = "detection"
    model_ref: str
    model_name: str
    config_ref: str
    scenario: str | None = None
    status: Literal["ok", "error"]
    frame_state: Literal["accepted", "doubt", "low", "no_detections", "error"]
    detections: list[DetectionRecord] = Field(default_factory=list)
    n_detections: int = Field(0, ge=0)
    zone_counts: dict[str, int] = Field(default_factory=dict)
    max_score: float | None = None
    mean_score: float | None = None
    inference_ms: float | None = None
    e2e_ms: float | None = Field(None, description="Decodificación del frame → evento registrado")
    degrade: dict[str, Any] | None = None
    origin: str | None = Field(None, description="Archivo de origen en reproducción")
    image_ref: str | None = Field(None, description="Ruta de la captura, relativa a la carpeta de la corrida")
    image_sha256: str | None = None
    capture_reason: str | None = None
    error: str | None = None

    def jsonl(self) -> str:
        return self.model_dump_json(exclude_none=False)


REQUIRED_TRACE_FIELDS = (
    "event_id",
    "run_id",
    "frame_id",
    "source_id",
    "timestamp",
    "model_ref",
    "config_ref",
)
