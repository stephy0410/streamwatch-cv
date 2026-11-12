"""Detector de objetos (Ultralytics YOLO11) con identidad verificable.

Ultralytics se importa de forma diferida: el resto del sistema (portal, reglas, métricas) y
las pruebas de CI funcionan sin PyTorch. Ver ``docs/MODELO.md``.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from streamwatch.config import ModelConfig

log = logging.getLogger(__name__)

MODELS_DIR = Path("models")


@dataclass(frozen=True)
class Detection:
    class_id: int
    class_name: str
    score: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 en píxeles de la imagen recibida

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["box"] = [round(v, 1) for v in self.box]
        d["score"] = float(self.score)  # sin redondear: la zona se decide con este valor exacto
        return d


@dataclass
class InferenceResult:
    detections: list[Detection]
    inference_ms: float  # preprocesado + modelo + NMS, medido con perf_counter
    breakdown_ms: dict[str, float] = field(default_factory=dict)


class Detector(Protocol):
    name: str
    model_ref: str
    device: str

    def predict(self, image: np.ndarray, classes: list[str]) -> InferenceResult: ...


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_device(preference: str) -> str:
    if preference != "auto":
        return preference
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def ensure_weights(weights: str) -> Path:
    """Devuelve la ruta local de los pesos; si faltan los descarga del release oficial."""
    path = Path(weights)
    if not path.is_absolute() and path.parent == Path("."):
        path = MODELS_DIR / path.name
    if path.exists():
        return path
    from ultralytics.utils.downloads import attempt_download_asset

    path.parent.mkdir(parents=True, exist_ok=True)
    downloaded = Path(attempt_download_asset(path.name))
    if downloaded.resolve() != path.resolve():
        shutil.move(str(downloaded), path)
    return path


class YoloDetector:
    def __init__(self, cfg: ModelConfig) -> None:
        from ultralytics import YOLO, __version__

        self.cfg = cfg
        self.name = cfg.name
        self.weights_path = ensure_weights(cfg.weights)
        self.sha256 = sha256_file(self.weights_path)
        if cfg.sha256 and cfg.sha256 != self.sha256:
            raise ValueError(
                f"SHA-256 de {self.weights_path} no coincide: esperado {cfg.sha256}, obtenido {self.sha256}"
            )
        if not cfg.sha256:
            log.warning("model.sha256 no está fijado; se registra el SHA observado %s", self.sha256)
        self.model_ref = f"{cfg.name}@sha256:{self.sha256[:12]}"
        self.ultralytics_version = __version__
        self.device = resolve_device(cfg.device)
        self.model = YOLO(str(self.weights_path))
        self.names: dict[int, str] = dict(self.model.names)
        self._ids_by_name = {v: k for k, v in self.names.items()}
        # Primera inferencia de calentamiento: no se mide para no sesgar la latencia.
        self.model.predict(np.zeros((cfg.imgsz, cfg.imgsz, 3), np.uint8), verbose=False, device=self.device)

    def class_ids(self, classes: list[str]) -> list[int] | None:
        if not classes:
            return None
        unknown = [c for c in classes if c not in self._ids_by_name]
        if unknown:
            raise ValueError(f"Clases que el modelo no conoce: {unknown}")
        return [self._ids_by_name[c] for c in classes]

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model_ref": self.model_ref,
            "weights": str(self.weights_path),
            "sha256": self.sha256,
            "framework": f"ultralytics {self.ultralytics_version}",
            "device": self.device,
            "imgsz": self.cfg.imgsz,
            "conf_floor": self.cfg.conf_floor,
            "iou": self.cfg.iou,
        }

    def predict(self, image: np.ndarray, classes: list[str]) -> InferenceResult:
        t0 = time.perf_counter()
        result = self.model.predict(
            image,
            conf=self.cfg.conf_floor,
            iou=self.cfg.iou,
            imgsz=self.cfg.imgsz,
            classes=self.class_ids(classes),
            device=self.device,
            verbose=False,
        )[0]
        elapsed = (time.perf_counter() - t0) * 1000.0
        boxes = result.boxes
        detections = [
            Detection(int(c), self.names[int(c)], float(s), tuple(float(v) for v in xyxy))
            for c, s, xyxy in zip(boxes.cls.tolist(), boxes.conf.tolist(), boxes.xyxy.tolist(), strict=True)
        ]
        detections.sort(key=lambda d: d.score, reverse=True)
        return InferenceResult(detections, elapsed, {k: round(v, 2) for k, v in result.speed.items()})
