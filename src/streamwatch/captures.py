"""Política de capturas: qué frames se guardan como imagen y por qué.

Se guarda la imagen **que recibió el modelo** (después de una degradación de escenario, si la
hubo), reducida a ``max_width``. Motivos, en orden de prioridad:

1. ``alert_opened``  — el frame que abrió una alerta (siempre, si ``on_alert``).
2. ``low_confidence`` — al menos ``low_conf_min_share`` de las detecciones del frame están en zona
   baja (un frame realmente dudoso); como máximo una cada ``low_conf_every_s`` por fuente.
3. ``normal_sample`` — muestra de operación normal, una cada ``normal_every_s`` por fuente.

No hay expiración automática: las capturas viven con su corrida y se exportan con ella.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np

from streamwatch.config import CapturesConfig


class CapturePolicy:
    def __init__(self, cfg: CapturesConfig) -> None:
        self.cfg = cfg
        self._last: dict[tuple[str, str], float] = {}

    def _due(self, source_id: str, reason: str, now: float, every_s: float) -> bool:
        last = self._last.get((source_id, reason))
        return last is None or now - last >= every_s

    def decide(self, source_id: str, now: float, n_low: int, n_total: int, alert_opened: bool) -> str | None:
        low_frame = n_total > 0 and n_low / n_total >= self.cfg.low_conf_min_share
        if alert_opened and self.cfg.on_alert:
            reason = "alert_opened"
        elif low_frame and self._due(source_id, "low_confidence", now, self.cfg.low_conf_every_s):
            reason = "low_confidence"
        elif self._due(source_id, "normal_sample", now, self.cfg.normal_every_s):
            reason = "normal_sample"
        else:
            return None
        self._last[(source_id, reason)] = now
        return reason


def save_capture(
    image: np.ndarray, run_dir: str | Path, source_id: str, seq: int, max_width: int, quality: int
) -> tuple[str, str, float]:
    """Guarda la imagen y devuelve (ruta relativa a la corrida, sha256, factor de escala)."""
    h, w = image.shape[:2]
    scale = min(1.0, max_width / w)
    if scale < 1.0:
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("No se pudo codificar la captura")
    data = buf.tobytes()
    rel = f"captures/{source_id}/{seq:06d}.jpg"
    path = Path(run_dir) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel, hashlib.sha256(data).hexdigest(), scale
