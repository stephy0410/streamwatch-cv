"""Métricas Prometheus del monitor (``/metrics`` en ``telemetry.prometheus_port``).

Se usa un registro propio para no mezclar métricas entre corridas o pruebas.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, Info, start_http_server

LATENCY_BUCKETS = (0.005, 0.01, 0.015, 0.02, 0.03, 0.05, 0.075, 0.1, 0.2, 0.5, 1.0, 2.5)
SCORE_BUCKETS = tuple(round(0.1 * i, 1) for i in range(1, 11))


class Telemetry:
    def __init__(self) -> None:
        r = self.registry = CollectorRegistry()
        self.frames = Counter("sw_frames_processed_total", "Frames procesados", ["source"], registry=r)
        self.errors = Counter("sw_inference_errors_total", "Inferencias fallidas", ["source"], registry=r)
        self.no_det = Counter("sw_frames_without_detections_total", "Frames sin detecciones", ["source"], registry=r)
        self.detections = Counter("sw_detections_total", "Detecciones por zona", ["source", "zone"], registry=r)
        self.inference = Histogram(
            "sw_inference_seconds", "Tiempo de inferencia", ["source", "model"], buckets=LATENCY_BUCKETS, registry=r
        )
        self.e2e = Histogram(
            "sw_e2e_seconds", "Frame decodificado → evento", ["source"], buckets=LATENCY_BUCKETS, registry=r
        )
        self.score = Histogram(
            "sw_detection_score", "Puntuación de detección", ["source"], buckets=SCORE_BUCKETS, registry=r
        )
        self.low_rate = Gauge(
            "sw_low_confidence_rate", "Proporción de baja confianza (ventana)", ["source"], registry=r
        )
        self.alerts_open = Gauge("sw_alerts_open", "Alertas abiertas", ["rule", "source"], registry=r)
        self.alerts_opened = Counter("sw_alerts_opened_total", "Alertas abiertas", ["rule", "source"], registry=r)
        self.frame_age = Gauge("sw_last_frame_age_seconds", "Antigüedad del último frame", ["source"], registry=r)
        self.captured = Gauge("sw_source_frames_read", "Frames decodificados por la fuente", ["source"], registry=r)
        self.reconnects = Gauge("sw_source_reconnects", "Reconexiones de la fuente", ["source"], registry=r)
        self.read_failures = Gauge("sw_source_read_failures", "Fallos de lectura", ["source"], registry=r)
        self.cpu = Gauge("sw_process_cpu_percent", "CPU del proceso (% de un núcleo)", registry=r)
        self.rss = Gauge("sw_process_rss_bytes", "Memoria residente del proceso", registry=r)
        self.info = Info("sw_monitor", "Identidad de la corrida", registry=r)

    def serve(self, port: int) -> None:
        start_http_server(port, registry=self.registry)
