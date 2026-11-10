"""Detector falso para pruebas: la puntuación depende del brillo de la imagen.

Imita lo observado con YOLO11s en la cámara real: con poca luz la confianza baja.
"""

from streamwatch.detector import Detection, InferenceResult


class BrightnessDetector:
    def __init__(self, name="yolo11s", n=4, fail_on=()):
        self.name = name
        self.model_ref = f"{name}@sha256:fake"
        self.device = "cpu"
        self.n = n
        self.fail_on = set(fail_on)
        self.calls = 0

    def describe(self):
        return {"name": self.name, "model_ref": self.model_ref, "device": self.device}

    def predict(self, image, classes):
        self.calls += 1
        if self.calls in self.fail_on:
            raise RuntimeError("fallo simulado de inferencia")
        b = float(image.mean()) / 255.0
        scores = [max(0.11, min(0.95, b - 0.05 * i)) for i in range(self.n)]
        dets = [Detection(18, "sheep", s, (10.0 * i, 10.0, 10.0 * i + 8, 18.0)) for i, s in enumerate(scores)]
        return InferenceResult(dets, inference_ms=5.0)
