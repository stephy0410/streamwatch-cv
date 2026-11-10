"""Consultas de solo lectura del portal sobre el SQLite del monitor."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

PAGE_SIZE = 50


@dataclass
class EventFilter:
    run_id: str | None = None
    source_id: str | None = None
    frame_state: str | None = None
    status: str | None = None
    has_image: bool = False
    alerted: bool = False
    degraded: bool | None = None
    since: str | None = None
    until: str | None = None
    page: int = 1
    params: dict[str, Any] = field(default_factory=dict)

    def where(self) -> tuple[str, list[Any]]:
        clauses, args = [], []
        for col in ("run_id", "source_id", "frame_state", "status"):
            value = getattr(self, col)
            if value:
                clauses.append(f"e.{col} = ?")
                args.append(value)
        if self.has_image:
            clauses.append("e.image_ref IS NOT NULL")
        if self.alerted:
            clauses.append("EXISTS (SELECT 1 FROM alert_events ae WHERE ae.event_id = e.event_id)")
        if self.degraded is not None:
            clauses.append("e.degraded = ?")
            args.append(int(self.degraded))
        if self.since:
            clauses.append("e.timestamp >= ?")
            args.append(self.since)
        if self.until:
            clauses.append("e.timestamp <= ?")
            args.append(self.until)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", args


def connect_ro(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(cur: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]


def runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    out = []
    for r in _rows(conn.execute("SELECT * FROM runs ORDER BY started_at DESC")):
        meta = json.loads(r.pop("meta") or "{}")
        r["meta"] = meta
        r["n_events"] = conn.execute("SELECT COUNT(*) FROM events WHERE run_id=?", (r["run_id"],)).fetchone()[0]
        r["n_alerts"] = conn.execute("SELECT COUNT(*) FROM alerts WHERE run_id=?", (r["run_id"],)).fetchone()[0]
        out.append(r)
    return out


def run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if not row:
        return None
    r = dict(row)
    r["meta"] = json.loads(r["meta"] or "{}")
    cfg = conn.execute("SELECT json FROM configs WHERE config_ref=?", (r["config_ref"],)).fetchone()
    r["config"] = json.loads(cfg[0]) if cfg else None
    return r


def events(conn: sqlite3.Connection, f: EventFilter, limit: int | None = PAGE_SIZE) -> tuple[list[dict], int]:
    where, args = f.where()
    total = conn.execute(f"SELECT COUNT(*) FROM events e{where}", args).fetchone()[0]
    sql = (
        "SELECT e.event_id, e.run_id, e.source_id, e.seq, e.timestamp, e.status, e.frame_state, e.n_detections,"
        " e.max_score, e.mean_score, e.n_low, e.n_doubt, e.n_accepted, e.inference_ms, e.e2e_ms, e.model_name,"
        " e.image_ref, e.capture_reason, e.degraded,"
        " (SELECT COUNT(*) FROM alert_events ae WHERE ae.event_id = e.event_id) AS n_alerts"
        f" FROM events e{where} ORDER BY e.timestamp DESC, e.event_id DESC"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)} OFFSET {int((max(f.page, 1) - 1) * limit)}"
    return _rows(conn.execute(sql, args)), total


def event(conn: sqlite3.Connection, event_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT json FROM events WHERE event_id=?", (event_id,)).fetchone()
    if not row:
        return None
    ev = json.loads(row[0])
    ev["alerts"] = _rows(
        conn.execute(
            "SELECT a.alert_id, a.rule_id, a.status, a.severity, a.opened_at FROM alerts a"
            " JOIN alert_events ae ON ae.alert_id = a.alert_id WHERE ae.event_id = ? ORDER BY a.opened_at",
            (event_id,),
        )
    )
    nb = conn.execute(
        "SELECT"
        " (SELECT event_id FROM events WHERE run_id=? AND source_id=? AND seq=?) AS prev,"
        " (SELECT event_id FROM events WHERE run_id=? AND source_id=? AND seq=?) AS next",
        (ev["run_id"], ev["source_id"], ev["seq"] - 1, ev["run_id"], ev["source_id"], ev["seq"] + 1),
    ).fetchone()
    ev["prev_id"], ev["next_id"] = nb["prev"], nb["next"]
    review = conn.execute("SELECT * FROM reviews WHERE event_id=?", (event_id,)).fetchone()
    ev["review"] = dict(review) if review else None
    return ev


def alerts(conn: sqlite3.Connection, status=None, rule_id=None, source_id=None, run_id=None) -> list[dict]:
    clauses, args = [], []
    for col, value in (("status", status), ("rule_id", rule_id), ("source_id", source_id), ("run_id", run_id)):
        if value:
            clauses.append(f"{col} = ?")
            args.append(value)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    out = []
    for r in _rows(conn.execute(f"SELECT json FROM alerts{where} ORDER BY opened_at DESC", args)):
        out.append(json.loads(r["json"]))
    return out


def alert(conn: sqlite3.Connection, alert_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT json FROM alerts WHERE alert_id=?", (alert_id,)).fetchone()
    if not row:
        return None
    a = json.loads(row[0])
    ids = [r[0] for r in conn.execute("SELECT event_id FROM alert_events WHERE alert_id=?", (alert_id,))]
    marks = ",".join("?" * len(ids)) or "''"
    a["events"] = _rows(
        conn.execute(
            "SELECT event_id, seq, timestamp, frame_state, n_detections, max_score, mean_score, n_low, n_doubt,"
            f" n_accepted, image_ref, capture_reason, degraded FROM events WHERE event_id IN ({marks}) ORDER BY seq",
            ids,
        )
    )
    a["evaluations"] = _rows(
        conn.execute(
            "SELECT timestamp, state, value FROM rule_evaluations WHERE run_id=? AND rule_id=? AND source_id=?"
            " AND timestamp >= ? AND timestamp <= COALESCE(?, '9999') ORDER BY timestamp LIMIT 400",
            (
                a["run_id"],
                a["rule_id"],
                a["source_id"],
                a["window"].get("start_ts") or a["opened_at"],
                a["resolved_at"],
            ),
        )
    )
    return a


def facets(conn: sqlite3.Connection) -> dict[str, list[str]]:
    def col(sql: str) -> list[str]:
        return [r[0] for r in conn.execute(sql) if r[0] is not None]

    return {
        "runs": col("SELECT run_id FROM runs ORDER BY started_at DESC"),
        "sources": col("SELECT DISTINCT source_id FROM events ORDER BY source_id"),
        "rules": col("SELECT DISTINCT rule_id FROM alerts ORDER BY rule_id"),
    }


def overview(conn: sqlite3.Connection) -> dict[str, Any]:
    latest = _rows(
        conn.execute(
            "SELECT e.source_id, e.run_id, e.event_id, e.timestamp, e.frame_state, e.max_score, e.n_detections,"
            " e.image_ref FROM events e JOIN (SELECT source_id, MAX(timestamp) ts FROM events GROUP BY source_id) m"
            " ON m.source_id = e.source_id AND m.ts = e.timestamp ORDER BY e.source_id"
        )
    )
    return {
        "latest": latest,
        "open_alerts": alerts(conn, status="open"),
        "counts": dict(
            conn.execute(
                "SELECT (SELECT COUNT(*) FROM events) events, (SELECT COUNT(*) FROM alerts) alerts,"
                " (SELECT COUNT(*) FROM runs) runs, (SELECT COUNT(*) FROM events WHERE image_ref IS NOT NULL) captures"
            ).fetchone()
        ),
    }
