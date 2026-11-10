"""Muestreo de recursos del proceso con psutil."""

from __future__ import annotations

import os

import psutil

from streamwatch.events import iso


class ResourceSampler:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.proc = psutil.Process(os.getpid())
        self.proc.cpu_percent(None)  # primera llamada: inicializa el contador
        psutil.cpu_percent(None)

    def sample(self, now: float) -> dict:
        mem = self.proc.memory_info()
        return {
            "run_id": self.run_id,
            "timestamp": iso(now),
            "process_cpu_percent": round(self.proc.cpu_percent(None), 2),  # % de un núcleo desde la muestra previa
            "process_rss_mb": round(mem.rss / 2**20, 1),
            "process_threads": self.proc.num_threads(),
            "system_cpu_percent": round(psutil.cpu_percent(None), 2),
            "system_mem_percent": round(psutil.virtual_memory().percent, 1),
            "cpu_count": psutil.cpu_count(),
        }
