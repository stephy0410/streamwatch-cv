"""Persistencia: registro JSONL por corrida (evidencia primaria) + SQLite (consulta del portal).

Estructura de una corrida (``data/runs/<run_id>/`` y, si se exporta, ``evidencias/runs/<run_id>/``)::

    run.json               metadatos: modelo, config_ref, escenario, revisión Git, inicio/fin
    config.json            configuración efectiva completa (reconstruye el config_ref)
    events.jsonl           un evento de inferencia por frame procesado
    alerts.jsonl           cambios de estado de alertas (opened / resolved); el último estado gana
    rule_evaluations.jsonl una evaluación por regla, fuente y frame
    resources.jsonl        muestras de CPU/RAM del proceso
    source_stats.jsonl     contadores de cada fuente (frames leídos, fallos, reconexiones)
    markers.jsonl          marcas de escenario (p. ej. inicio de la degradación)
    captures/<source>/*.jpg imágenes vinculadas a eventos

El SQLite se puede reconstruir siempre desde los JSONL con ``streamwatch import``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, ClassVar

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, started_at TEXT, ended_at TEXT, scenario TEXT, config_ref TEXT,
    model_ref TEXT, root_dir TEXT, meta TEXT
);
CREATE TABLE IF NOT EXISTS configs (config_ref TEXT PRIMARY KEY, json TEXT);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY, run_id TEXT, source_id TEXT, seq INTEGER, frame_id TEXT, timestamp TEXT,
    captured_at TEXT, status TEXT, frame_state TEXT, n_detections INTEGER, max_score REAL, mean_score REAL,
    n_low INTEGER, n_doubt INTEGER, n_accepted INTEGER, inference_ms REAL, e2e_ms REAL, model_ref TEXT,
    model_name TEXT, config_ref TEXT, scenario TEXT, degraded INTEGER, image_ref TEXT, capture_reason TEXT,
    json TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_run_source ON events(run_id, source_id, seq);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(timestamp);
CREATE TABLE IF NOT EXISTS detections (
    event_id TEXT, idx INTEGER, class_name TEXT, score REAL, zone TEXT, PRIMARY KEY (event_id, idx)
);
CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY, run_id TEXT, rule_id TEXT, source_id TEXT, status TEXT, severity TEXT,
    opened_at TEXT, resolved_at TEXT, json TEXT
);
CREATE TABLE IF NOT EXISTS alert_events (alert_id TEXT, event_id TEXT, PRIMARY KEY (alert_id, event_id));
CREATE INDEX IF NOT EXISTS ix_alert_events_event ON alert_events(event_id);
CREATE TABLE IF NOT EXISTS rule_evaluations (
    run_id TEXT, rule_id TEXT, source_id TEXT, timestamp TEXT, state TEXT, value REAL, json TEXT
);
CREATE INDEX IF NOT EXISTS ix_evals ON rule_evaluations(run_id, source_id, rule_id, timestamp);
CREATE TABLE IF NOT EXISTS resource_samples (run_id TEXT, timestamp TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS source_samples (run_id TEXT, source_id TEXT, timestamp TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS markers (run_id TEXT, timestamp TEXT, kind TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS reviews (
    event_id TEXT PRIMARY KEY, reviewed_at TEXT, verdict TEXT, note TEXT
);
"""

RUN_TABLES = ("events", "alerts", "rule_evaluations", "resource_samples", "source_samples", "markers")


def connect(db_path: str | Path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def read_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


class Store:
    """Escritura en SQLite. Segura para un escritor con varios hilos (candado interno)."""

    def __init__(self, db_path: str | Path) -> None:
        self.conn = connect(db_path)
        self._lock = threading.Lock()

    def close(self) -> None:
        self.conn.close()

    # --- escritura ----------------------------------------------------------------------
    def upsert_run(self, meta: dict[str, Any], root_dir: str | Path) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?)",
                (
                    meta["run_id"],
                    meta.get("started_at"),
                    meta.get("ended_at"),
                    meta.get("scenario"),
                    meta.get("config_ref"),
                    meta.get("model_ref"),
                    str(root_dir),
                    json.dumps(meta),
                ),
            )

    def upsert_config(self, config_ref: str, config: dict[str, Any]) -> None:
        with self._lock, self.conn:
            self.conn.execute("INSERT OR REPLACE INTO configs VALUES (?,?)", (config_ref, json.dumps(config)))

    def add_events(self, events: Iterable[dict[str, Any]]) -> None:
        rows, dets = [], []
        for e in events:
            zc = e.get("zone_counts") or {}
            rows.append(
                (
                    e["event_id"],
                    e["run_id"],
                    e["source_id"],
                    e["seq"],
                    e["frame_id"],
                    e["timestamp"],
                    e["captured_at"],
                    e["status"],
                    e["frame_state"],
                    e["n_detections"],
                    e.get("max_score"),
                    e.get("mean_score"),
                    zc.get("low", 0),
                    zc.get("doubt", 0),
                    zc.get("accepted", 0),
                    e.get("inference_ms"),
                    e.get("e2e_ms"),
                    e["model_ref"],
                    e["model_name"],
                    e["config_ref"],
                    e.get("scenario"),
                    int(e.get("degrade") is not None),
                    e.get("image_ref"),
                    e.get("capture_reason"),
                    json.dumps(e),
                )
            )
            dets.extend(
                (e["event_id"], i, d["class_name"], d["score"], d["zone"])
                for i, d in enumerate(e["detections"])
            )
        with self._lock, self.conn:
            self.conn.executemany(f"INSERT OR REPLACE INTO events VALUES ({','.join('?' * 25)})", rows)
            self.conn.executemany("INSERT OR REPLACE INTO detections VALUES (?,?,?,?,?)", dets)

    def upsert_alert(self, alert: dict[str, Any]) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO alerts VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    alert["alert_id"],
                    alert["run_id"],
                    alert["rule_id"],
                    alert["source_id"],
                    alert["status"],
                    alert["severity"],
                    alert["opened_at"],
                    alert.get("resolved_at"),
                    json.dumps(alert),
                ),
            )
            self.conn.executemany(
                "INSERT OR IGNORE INTO alert_events VALUES (?,?)",
                [(alert["alert_id"], ev) for ev in alert.get("event_ids", [])],
            )

    def add_rows(self, table: str, rows: Iterable[dict[str, Any]]) -> None:
        rows = list(rows)
        if not rows:
            return
        with self._lock, self.conn:
            if table == "rule_evaluations":
                self.conn.executemany(
                    "INSERT INTO rule_evaluations VALUES (?,?,?,?,?,?,?)",
                    [
                        (
                            r["run_id"],
                            r["rule_id"],
                            r["source_id"],
                            r["timestamp"],
                            r["state"],
                            r.get("value"),
                            json.dumps(r),
                        )
                        for r in rows
                    ],
                )
            elif table == "resource_samples":
                self.conn.executemany(
                    "INSERT INTO resource_samples VALUES (?,?,?)",
                    [(r["run_id"], r["timestamp"], json.dumps(r)) for r in rows],
                )
            elif table == "source_samples":
                self.conn.executemany(
                    "INSERT INTO source_samples VALUES (?,?,?,?)",
                    [(r["run_id"], r["source_id"], r["timestamp"], json.dumps(r)) for r in rows],
                )
            elif table == "markers":
                self.conn.executemany(
                    "INSERT INTO markers VALUES (?,?,?,?)",
                    [(r["run_id"], r["timestamp"], r["kind"], json.dumps(r)) for r in rows],
                )
            else:
                raise ValueError(table)

    def delete_run(self, run_id: str) -> None:
        with self._lock, self.conn:
            ids = [r[0] for r in self.conn.execute("SELECT alert_id FROM alerts WHERE run_id=?", (run_id,))]
            self.conn.executemany("DELETE FROM alert_events WHERE alert_id=?", [(i,) for i in ids])
            self.conn.execute(
                "DELETE FROM detections WHERE event_id IN (SELECT event_id FROM events WHERE run_id=?)",
                (run_id,),
            )
            for table in RUN_TABLES:
                self.conn.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
            self.conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))


class RunRecorder:
    """Escribe una corrida en JSONL (fuente primaria) y la refleja en SQLite."""

    FILES: ClassVar[dict[str, str]] = {
        "events": "events.jsonl",
        "alerts": "alerts.jsonl",
        "rule_evaluations": "rule_evaluations.jsonl",
        "resource_samples": "resources.jsonl",
        "source_samples": "source_stats.jsonl",
        "markers": "markers.jsonl",
    }

    def __init__(self, root: str | Path, store: Store | None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "captures").mkdir(exist_ok=True)
        self.store = store
        self._lock = threading.Lock()
        self._fh = {k: (self.root / v).open("a", encoding="utf-8") for k, v in self.FILES.items()}

    def _write(self, kind: str, obj: dict[str, Any]) -> None:
        with self._lock:
            self._fh[kind].write(json.dumps(obj, ensure_ascii=False) + "\n")
            self._fh[kind].flush()

    def start(self, meta: dict[str, Any], config: dict[str, Any]) -> None:
        (self.root / "config.json").write_text(
            json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self.write_meta(meta)
        if self.store:
            self.store.upsert_config(meta["config_ref"], config)

    def write_meta(self, meta: dict[str, Any]) -> None:
        (self.root / "run.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        if self.store:
            self.store.upsert_run(meta, self.root)

    def event(self, event: dict[str, Any]) -> None:
        self._write("events", event)
        if self.store:
            self.store.add_events([event])

    def alert(self, alert: dict[str, Any]) -> None:
        self._write("alerts", alert)
        if self.store:
            self.store.upsert_alert(alert)

    def rows(self, kind: str, rows: list[dict[str, Any]]) -> None:
        for r in rows:
            self._write(kind, r)
        if self.store:
            self.store.add_rows(kind, rows)

    def close(self) -> None:
        for fh in self._fh.values():
            fh.close()


def import_run(store: Store, run_dir: str | Path) -> dict[str, int]:
    """Carga una corrida exportada (JSONL) en SQLite. Es idempotente."""
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    store.delete_run(meta["run_id"])
    store.upsert_run(meta, run_dir)
    config_path = run_dir / "config.json"
    if config_path.exists():
        store.upsert_config(meta["config_ref"], json.loads(config_path.read_text(encoding="utf-8")))
    counts: dict[str, int] = {}
    events = list(read_jsonl(run_dir / "events.jsonl"))
    store.add_events(events)
    counts["events"] = len(events)
    latest: dict[str, dict[str, Any]] = {}
    for a in read_jsonl(run_dir / "alerts.jsonl"):
        latest[a["alert_id"]] = a
    for a in latest.values():
        store.upsert_alert(a)
    counts["alerts"] = len(latest)
    for kind, fname in RunRecorder.FILES.items():
        if kind in ("events", "alerts"):
            continue
        rows = list(read_jsonl(run_dir / fname))
        store.add_rows(kind, rows)
        counts[kind] = len(rows)
    return counts
