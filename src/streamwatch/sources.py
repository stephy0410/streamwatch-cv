"""Fuentes de video.

Cada fuente corre un hilo lector que consume el stream a su ritmo natural y conserva solo el
último frame decodificado. El monitor toma ese frame cada ``sampling.interval_s``; los frames
intermedios se cuentan como *descartados por muestreo*. Así la latencia no se acumula aunque
el modelo sea más lento que el video.

Tipos soportados: ``youtube`` (se resuelve la URL HLS con yt-dlp), ``stream`` (URL directa,
RTSP/HLS), ``webcam`` (índice de cámara), ``video`` (archivo) e ``images`` (carpeta de JPEG/PNG).
Los dos últimos se reproducen a ``replay_fps`` para repetir una corrida sin la cámara.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np

from streamwatch.config import FaultConfig, SourceConfig

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


@dataclass(frozen=True)
class Frame:
    source_id: str
    read_index: int  # n-ésimo frame leído de la fuente desde que arrancó
    image: np.ndarray
    captured_at: float  # epoch (s) en que se decodificó
    origin: str = ""  # nombre de archivo en reproducción; vacío en vivo


@dataclass
class SourceStats:
    frames_read: int = 0
    read_failures: int = 0
    reconnects: int = 0
    connected: bool = False
    in_outage: bool = False
    last_frame_at: float | None = None
    started_at: float | None = None
    exhausted: bool = False
    last_error: str = ""

    def snapshot(self) -> dict[str, Any]:
        return dict(self.__dict__)


class Capture(Protocol):
    def isOpened(self) -> bool: ...
    def read(self) -> tuple[bool, np.ndarray | None]: ...
    def release(self) -> None: ...


def resolve_youtube(url: str, max_height: int = 720, timeout: float = 90.0) -> str:
    """Devuelve la URL HLS de una transmisión de YouTube usando yt-dlp."""
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--socket-timeout", "20", "-g"]
    cmd += ["-f", f"bestvideo[height<={max_height}]/best[height<={max_height}]"]
    if shutil.which("node"):
        cmd += ["--js-runtimes", "node"]
    out = subprocess.run([*cmd, url], capture_output=True, text=True, timeout=timeout)
    lines = [ln for ln in out.stdout.splitlines() if ln.startswith("http")]
    if out.returncode != 0 or not lines:
        raise RuntimeError(f"yt-dlp no pudo resolver {url}: {out.stderr.strip()[-300:]}")
    return lines[0]


def in_fault_window(faults: list[FaultConfig], elapsed_s: float) -> bool:
    return any(f.start_after_s <= elapsed_s < f.start_after_s + f.duration_s for f in faults)


class FrameSource:
    """Base: hilo lector + último frame protegido por candado."""

    def __init__(self, cfg: SourceConfig, clock: Callable[[], float] = time.time) -> None:
        self.cfg = cfg
        self.id = cfg.id
        self.clock = clock
        self.stats = SourceStats()
        self._latest: Frame | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- ciclo de vida -------------------------------------------------------------------
    def start(self) -> None:
        self.stats.started_at = self.clock()
        self._thread = threading.Thread(target=self._run_safe, name=f"src-{self.id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def latest(self) -> Frame | None:
        with self._lock:
            return self._latest

    def elapsed(self) -> float:
        return self.clock() - (self.stats.started_at or self.clock())

    def _publish(self, image: np.ndarray, origin: str = "") -> None:
        now = self.clock()
        with self._lock:
            self.stats.frames_read += 1
            self.stats.last_frame_at = now
            self._latest = Frame(self.id, self.stats.frames_read, image, now, origin)

    def _run_safe(self) -> None:
        try:
            self._run()
        except Exception as exc:  # el hilo nunca debe morir en silencio
            log.exception("Fuente %s terminó con error", self.id)
            self.stats.last_error = repr(exc)

    def _run(self) -> None:  # pragma: no cover - implementado por subclases
        raise NotImplementedError


class LiveSource(FrameSource):
    """Cámara en vivo (YouTube/HLS/RTSP/webcam) con reconexión y backoff exponencial."""

    MAX_CONSECUTIVE_FAILURES = 5

    def __init__(
        self,
        cfg: SourceConfig,
        clock: Callable[[], float] = time.time,
        opener: Callable[[Any], Capture] = cv2.VideoCapture,
        resolver: Callable[[str], str] = resolve_youtube,
        max_backoff_s: float = 10.0,
    ) -> None:
        super().__init__(cfg, clock)
        self.opener = opener
        self.resolver = resolver
        self.max_backoff_s = max_backoff_s

    def _target(self) -> Any:
        if self.cfg.kind == "youtube":
            return self.resolver(self.cfg.uri)
        if self.cfg.kind == "webcam":
            return int(self.cfg.uri)
        return self.cfg.uri

    def _open(self) -> Capture | None:
        try:
            cap = self.opener(self._target())
        except Exception as exc:
            self.stats.last_error = repr(exc)
            return None
        if cap is None or not cap.isOpened():
            self.stats.last_error = "no se pudo abrir la fuente"
            return None
        return cap

    def _run(self) -> None:
        cap: Capture | None = None
        backoff = 1.0
        failures = 0
        first_connection = True
        while not self._stop.is_set():
            if in_fault_window(self.cfg.faults, self.elapsed()):
                if cap is not None:  # la falla corta la conexión real
                    cap.release()
                    cap = None
                self.stats.connected = False
                self.stats.in_outage = True
                self._stop.wait(0.2)
                continue
            self.stats.in_outage = False
            if cap is None:
                cap = self._open()
                if cap is None:
                    self.stats.connected = False
                    self._stop.wait(backoff)
                    backoff = min(backoff * 2, self.max_backoff_s)
                    continue
                if not first_connection:
                    self.stats.reconnects += 1
                first_connection = False
                self.stats.connected = True
                backoff, failures = 1.0, 0
            ok, image = cap.read()
            if ok and image is not None:
                failures = 0
                self._publish(image)
                continue
            failures += 1
            self.stats.read_failures += 1
            if failures >= self.MAX_CONSECUTIVE_FAILURES:
                cap.release()
                cap = None
                self.stats.connected = False
            self._stop.wait(0.05)
        if cap is not None:
            cap.release()


class ReplaySource(FrameSource):
    """Reproduce un archivo de video o una carpeta de imágenes a ``replay_fps``."""

    def __init__(self, cfg: SourceConfig, clock: Callable[[], float] = time.time, loop: bool = False) -> None:
        super().__init__(cfg, clock)
        self.fps = cfg.replay_fps or 1.0
        self.loop = loop

    def _frames(self):
        path = Path(self.cfg.uri)
        if self.cfg.kind == "images":
            files = sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
            for p in files:
                image = cv2.imread(str(p))
                if image is None:
                    self.stats.read_failures += 1
                    continue
                yield image, p.name
        else:
            cap = cv2.VideoCapture(str(path))
            try:
                while True:
                    ok, image = cap.read()
                    if not ok:
                        break
                    yield image, path.name
            finally:
                cap.release()

    def _run(self) -> None:
        period = 1.0 / self.fps
        while not self._stop.is_set():
            produced = False
            for image, origin in self._frames():
                if self._stop.is_set():
                    return
                while in_fault_window(self.cfg.faults, self.elapsed()) and not self._stop.is_set():
                    self.stats.connected, self.stats.in_outage = False, True
                    self._stop.wait(0.2)
                self.stats.connected, self.stats.in_outage = True, False
                self._publish(image, origin)
                produced = True
                self._stop.wait(period)
            if not self.loop or not produced:
                break
        self.stats.exhausted = True
        self.stats.connected = False


def build_source(cfg: SourceConfig, **kwargs: Any) -> FrameSource:
    if cfg.kind in ("video", "images"):
        return ReplaySource(cfg, **kwargs)
    return LiveSource(cfg, **kwargs)


# --- Transformación de entrada (escenarios de iluminación) ----------------------------------


@dataclass
class DegradeResult:
    image: np.ndarray
    applied: dict[str, Any] | None = field(default=None)


def apply_degrade(image: np.ndarray, cfg, elapsed_s: float) -> DegradeResult:
    """Simula poca luz: ``(x/255)^gamma * brightness`` más ruido gaussiano de sensor.

    Con ``ramp_s`` > 0 la intensidad crece linealmente (atardecer). La puntuación del modelo
    nunca se toca: solo cambia la imagen de entrada, y los parámetros quedan en el evento.
    """
    if cfg is None or elapsed_s < cfg.start_after_s:
        return DegradeResult(image, None)
    k = 1.0 if cfg.ramp_s <= 0 else min(1.0, (elapsed_s - cfg.start_after_s) / cfg.ramp_s)
    brightness = 1.0 + (cfg.brightness - 1.0) * k
    gamma = 1.0 + (cfg.gamma - 1.0) * k
    sigma = cfg.noise_sigma * k
    x = (image.astype(np.float32) / 255.0) ** gamma * brightness * 255.0
    if sigma > 0:
        rng = np.random.default_rng(cfg.seed + int(elapsed_s * 1000))
        x += rng.normal(0.0, sigma, x.shape).astype(np.float32)
    out = np.clip(x, 0, 255).astype(np.uint8)
    applied = {
        "kind": cfg.kind,
        "intensity": round(k, 3),
        "brightness": round(brightness, 3),
        "gamma": round(gamma, 3),
        "noise_sigma": round(sigma, 2),
    }
    return DegradeResult(out, applied)
