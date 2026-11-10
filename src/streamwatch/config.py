"""Configuración versionada del monitor.

La configuración vive en YAML (``config/monitor.yaml``) y los escenarios la sobrescriben
con un *overlay* (``config/scenarios/*.yaml``). La configuración efectiva se valida con
Pydantic y se identifica con ``config_ref = <config_id>@<sha256[:12]>`` para que cada evento
y cada alerta indiquen exactamente con qué umbrales, ventanas y modelo se produjeron.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DegradeConfig(_Strict):
    """Transformación de iluminación aplicada a la entrada (escenarios de baja confianza).

    La puntuación nunca se modifica: solo cambia la imagen que recibe el modelo.
    ``ramp_s`` > 0 aplica la transformación de forma gradual (simula un atardecer).
    """

    kind: Literal["lowlight"] = "lowlight"
    start_after_s: float = Field(0.0, ge=0)
    brightness: float = Field(0.2, gt=0, le=1)
    gamma: float = Field(3.0, ge=1)
    noise_sigma: float = Field(14.0, ge=0)
    ramp_s: float = Field(0.0, ge=0)
    seed: int = 0


class FaultConfig(_Strict):
    """Inyección controlada de fallas de la fuente (escenario de interrupción)."""

    kind: Literal["outage"] = "outage"
    start_after_s: float = Field(..., ge=0)
    duration_s: float = Field(..., gt=0)


class SourceConfig(_Strict):
    id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]*$")
    kind: Literal["youtube", "stream", "video", "images", "webcam"]
    uri: str
    title: str = ""
    domain: str = ""
    attribution: str = ""
    classes: list[str] = Field(default_factory=list, description="Clases COCO que se monitorean")
    enabled: bool = True
    replay_fps: float | None = Field(None, gt=0, description="Ritmo de reproducción para video/imágenes")
    degrade: DegradeConfig | None = None
    faults: list[FaultConfig] = Field(default_factory=list)


class SamplingConfig(_Strict):
    interval_s: float = Field(1.0, gt=0, description="Un frame por fuente cada interval_s segundos")


class ModelConfig(_Strict):
    name: str
    weights: str
    sha256: str | None = None
    expected_name: str | None = Field(None, description="Versión que se espera en producción")
    imgsz: int = Field(640, ge=32)
    conf_floor: float = Field(0.10, ge=0, lt=1, description="Piso de salida del detector")
    iou: float = Field(0.45, gt=0, le=1, description="Umbral IoU de NMS")
    device: str = "auto"


class ConfidenceConfig(_Strict):
    lower: float = Field(..., ge=0, le=1)
    upper: float = Field(..., ge=0, le=1)
    reference: str | None = None

    @model_validator(mode="after")
    def _ordered(self) -> ConfidenceConfig:
        if not self.lower < self.upper:
            raise ValueError("Se requiere 0 <= lower < upper <= 1")
        return self


class LowConfidenceRule(_Strict):
    window_frames: int = Field(20, ge=1)
    min_detections: int = Field(15, ge=1)
    rate_threshold: float = Field(0.6, gt=0, le=1)
    persistence: int = Field(3, ge=1)
    clear_after: int = Field(5, ge=1)
    severity: Literal["info", "warning", "critical"] = "warning"
    per_source_threshold: dict[str, float] = Field(default_factory=dict)


class ConfidenceShiftRule(_Strict):
    window_frames: int = Field(60, ge=1)
    min_detections: int = Field(40, ge=1)
    tolerance: float = Field(0.10, gt=0, le=1)
    persistence: int = Field(15, ge=1)
    clear_after: int = Field(10, ge=1)
    severity: Literal["info", "warning", "critical"] = "warning"


class StreamStaleRule(_Strict):
    max_age_s: float = Field(15.0, gt=0)
    severity: Literal["info", "warning", "critical"] = "critical"


class ModelVersionRule(_Strict):
    enabled: bool = True
    severity: Literal["info", "warning", "critical"] = "critical"


class AlertsConfig(_Strict):
    low_confidence: LowConfidenceRule = LowConfidenceRule()
    confidence_shift: ConfidenceShiftRule = ConfidenceShiftRule()
    stream_stale: StreamStaleRule = StreamStaleRule()
    model_version: ModelVersionRule = ModelVersionRule()


class CapturesConfig(_Strict):
    normal_every_s: float = Field(60.0, gt=0)
    low_conf_every_s: float = Field(10.0, gt=0)
    on_alert: bool = True
    max_width: int = Field(960, ge=64)
    jpeg_quality: int = Field(80, ge=10, le=100)


class StorageConfig(_Strict):
    db: str = "data/streamwatch.db"
    runs_dir: str = "data/runs"
    live_dir: str = "data/live"


class TelemetryConfig(_Strict):
    prometheus_port: int | None = 9108
    resource_every_s: float = Field(5.0, gt=0)
    source_stats_every_s: float = Field(5.0, gt=0)


class MonitorConfig(_Strict):
    config_id: str
    sources: list[SourceConfig]
    sampling: SamplingConfig = SamplingConfig()
    model: ModelConfig
    confidence: ConfidenceConfig
    alerts: AlertsConfig = AlertsConfig()
    captures: CapturesConfig = CapturesConfig()
    storage: StorageConfig = StorageConfig()
    telemetry: TelemetryConfig = TelemetryConfig()
    scenario: str | None = None

    @model_validator(mode="after")
    def _unique_sources(self) -> MonitorConfig:
        ids = [s.id for s in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("Los id de fuente deben ser únicos")
        if not any(s.enabled for s in self.sources):
            raise ValueError("Se requiere al menos una fuente habilitada")
        return self

    @property
    def active_sources(self) -> list[SourceConfig]:
        return [s for s in self.sources if s.enabled]

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()

    @property
    def config_ref(self) -> str:
        return f"{self.config_id}@{self.sha256[:12]}"


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Combina diccionarios recursivamente. Las listas de fuentes se combinan por ``id``."""
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if key == "sources" and isinstance(value, list) and isinstance(out.get(key), list):
            by_id = {s["id"]: s for s in out[key]}
            for src in value:
                if src["id"] in by_id:
                    by_id[src["id"]] = deep_merge(by_id[src["id"]], src)
                else:
                    by_id[src["id"]] = src
            out[key] = list(by_id.values())
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_config(path: str | Path, overlay: str | Path | None = None) -> MonitorConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if overlay is not None:
        data = deep_merge(data, yaml.safe_load(Path(overlay).read_text(encoding="utf-8")))
    return MonitorConfig.model_validate(data)
