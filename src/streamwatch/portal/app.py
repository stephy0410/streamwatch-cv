"""Portal de monitoreo (FastAPI + Jinja2, renderizado en servidor, sin dependencias de JS).

Vistas obligatorias: consulta de eventos y de alertas, con vínculos hasta la imagen, la
configuración y los eventos que originaron cada alerta. API JSON equivalente en ``/api``.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from streamwatch import __version__
from streamwatch.portal import queries as q
from streamwatch.portal.charts import line_chart
from streamwatch.storage import connect

HERE = Path(__file__).parent

STATE_LABELS = {
    "accepted": "Aceptada",
    "doubt": "Duda",
    "low": "Baja",
    "no_detections": "Sin detecciones",
    "error": "Error",
}
RULE_LABELS = {
    "low-confidence-v1": "Baja confianza",
    "confidence-shift-v1": "Cambio sostenido",
    "stream-stale-v1": "Fuente sin frames",
    "model-version-v1": "Versión de modelo",
}


VERDICTS = {
    "confirmada": "Causa visible (luz, oclusión, escena)",
    "sin_problema": "Frame normal: la duda no tiene causa visible",
    "falsa_alarma": "Falsa alarma de la regla",
    "ilegible": "Imagen ilegible",
}
EXPORT_COLUMNS = [
    "event_id",
    "run_id",
    "source_id",
    "seq",
    "timestamp",
    "status",
    "frame_state",
    "n_detections",
    "n_low",
    "n_doubt",
    "n_accepted",
    "max_score",
    "mean_score",
    "inference_ms",
    "e2e_ms",
    "model_name",
    "degraded",
    "image_ref",
    "capture_reason",
    "n_alerts",
]


def _rolling(values: list[float | None], n: int = 10) -> list[float | None]:
    out, buf = [], []
    for v in values:
        if v is not None:
            buf.append(v)
            buf = buf[-n:]
        out.append(sum(buf) / len(buf) if buf else None)
    return out


def _flag(value: str | None) -> bool:
    return value in ("1", "true", "on", "yes")


def create_app(db_path: str = "data/streamwatch.db", live_dir: str = "data/live") -> FastAPI:
    connect(db_path).close()  # crea el esquema si el SQLite aún no existe
    app = FastAPI(title="StreamWatch CV", version=__version__)
    app.state.db_path = db_path
    app.state.live_dir = Path(live_dir)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals.update(
        STATE_LABELS=STATE_LABELS, RULE_LABELS=RULE_LABELS, VERDICTS=VERDICTS, version=__version__
    )
    templates.env.filters["pct"] = lambda v: "—" if v is None else f"{v * 100:.0f}%"
    templates.env.filters["num"] = lambda v, d=2: "—" if v is None else f"{v:.{d}f}"
    templates.env.filters["short_ts"] = lambda v: "—" if not v else v.replace("T", " ")[:19]
    templates.env.filters["tojson_pretty"] = lambda v: json.dumps(v, indent=2, ensure_ascii=False)
    app.state.templates = templates

    def db():
        return q.connect_ro(app.state.db_path)

    def render(request: Request, name: str, **ctx: Any) -> HTMLResponse:
        return templates.TemplateResponse(request, name, ctx)

    def event_filter(request: Request) -> q.EventFilter:
        p = request.query_params
        degraded = p.get("degraded")
        return q.EventFilter(
            run_id=p.get("run_id") or None,
            source_id=p.get("source_id") or None,
            frame_state=p.get("frame_state") or None,
            status=p.get("status") or None,
            has_image=_flag(p.get("has_image")),
            alerted=_flag(p.get("alerted")),
            degraded=None if not degraded else _flag(degraded),
            since=p.get("since") or None,
            until=p.get("until") or None,
            page=int(p.get("page") or 1),
        )

    # --- páginas ------------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        with db() as conn:
            return render(request, "home.html", ov=q.overview(conn), runs=q.runs(conn))

    @app.get("/events", response_class=HTMLResponse)
    def events_page(request: Request):
        f = event_filter(request)
        with db() as conn:
            rows, total = q.events(conn, f)
            facets = q.facets(conn)
        params = {k: v for k, v in request.query_params.items() if k != "page" and v}
        pages = max(1, -(-total // q.PAGE_SIZE))
        return render(
            request,
            "events.html",
            rows=rows,
            total=total,
            f=f,
            facets=facets,
            pages=pages,
            qs=urlencode(params),
        )

    @app.get("/events/{event_id}", response_class=HTMLResponse)
    def event_page(request: Request, event_id: str):
        with db() as conn:
            ev = q.event(conn, event_id)
            if not ev:
                raise HTTPException(404, "Evento no encontrado")
            run = q.run(conn, ev["run_id"])
        return render(request, "event.html", ev=ev, run=run)

    @app.get("/alerts", response_class=HTMLResponse)
    def alerts_page(
        request: Request,
        status: str | None = None,
        rule_id: str | None = None,
        source_id: str | None = None,
        run_id: str | None = None,
    ):
        with db() as conn:
            rows = q.alerts(conn, status or None, rule_id or None, source_id or None, run_id or None)
            facets = q.facets(conn)
        sel = {"status": status, "rule_id": rule_id, "source_id": source_id, "run_id": run_id}
        return render(request, "alerts.html", rows=rows, facets=facets, sel=sel)

    @app.get("/alerts/{alert_id}", response_class=HTMLResponse)
    def alert_page(request: Request, alert_id: str):
        with db() as conn:
            a = q.alert(conn, alert_id)
            if not a:
                raise HTTPException(404, "Alerta no encontrada")
        chart = None
        series = [(v["timestamp"], v["value"] if v["state"] in ("ok", "breach") else None) for v in a["evaluations"]]
        if any(v is not None for _, v in series):
            hl = [(a["threshold"], "umbral", "#b54708")] if a.get("threshold") is not None else []
            chart = line_chart(
                {a["source_id"]: series},
                f"{a['rule_id']}: valor evaluado (huecos = evidencia insuficiente)",
                "valor",
                0,
                None,
                hl,
                [(a["opened_at"], a["resolved_at"], a["alert_id"])],
            )
        return render(request, "alert.html", a=a, chart=chart)

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_page(request: Request, run_id: str):
        with db() as conn:
            run = q.run(conn, run_id)
            if not run:
                raise HTTPException(404, "Corrida no encontrada")
            alerts = q.alerts(conn, run_id=run_id)
        return render(request, "run.html", run=run, alerts=alerts)

    @app.get("/captures/{run_id}/{path:path}")
    def capture(run_id: str, path: str):
        with db() as conn:
            row = conn.execute("SELECT root_dir FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        root = Path(row[0]).resolve()
        target = (root / path).resolve()
        if root not in target.parents or not target.is_file():  # evita recorrer fuera de la corrida
            raise HTTPException(404)
        return FileResponse(target, media_type="image/jpeg")

    # --- extras: exportación, galería, revisión, dashboard y vista en vivo --------------
    @app.get("/events.{fmt}")
    def export_events(request: Request, fmt: str):
        if fmt not in ("csv", "jsonl"):
            raise HTTPException(404)
        f = event_filter(request)
        with db() as conn:
            rows, _ = q.events(conn, f, limit=None)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        headers = {"Content-Disposition": f'attachment; filename="eventos-{stamp}.{fmt}"'}
        if fmt == "jsonl":
            body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
            return Response(body, media_type="application/x-ndjson", headers=headers)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return Response(buf.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)

    @app.get("/captures", response_class=HTMLResponse)
    def gallery(
        request: Request,
        run_id: str | None = None,
        source_id: str | None = None,
        reason: str | None = None,
        reviewed: str | None = None,
    ):
        with db() as conn:
            rows = q.captures(conn, run_id or None, source_id or None, reason or None, reviewed or None)
            facets = q.facets(conn)
        sel = {"run_id": run_id, "source_id": source_id, "reason": reason, "reviewed": reviewed}
        return render(request, "captures.html", rows=rows, facets=facets, sel=sel)

    @app.post("/events/{event_id}/review")
    def review(event_id: str, verdict: str = Form(...), note: str = Form("")):
        if verdict not in VERDICTS:
            raise HTTPException(422, "Veredicto no válido")
        conn = connect(app.state.db_path)
        try:
            if not conn.execute("SELECT 1 FROM events WHERE event_id=?", (event_id,)).fetchone():
                raise HTTPException(404, "Evento no encontrado")
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO reviews VALUES (?,?,?,?)",
                    (event_id, datetime.now(UTC).isoformat(timespec="seconds"), verdict, note.strip()[:500]),
                )
        finally:
            conn.close()
        return RedirectResponse(f"/events/{event_id}#revision", status_code=303)

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request, run_id: str | None = None):
        with db() as conn:
            facets = q.facets(conn)
            run_id = run_id or (facets["runs"][0] if facets["runs"] else None)
            run = q.run(conn, run_id) if run_id else None
            data = q.dashboard(conn, run_id) if run else None
        charts, metrics = [], None
        if run and data:
            thr = run["meta"].get("thresholds", {})
            spans = [(a["opened_at"], a["resolved_at"], a["alert_id"]) for a in data["alerts"]]
            conf = {s: list(zip(d["ts"], _rolling(d["mean"]), strict=True)) for s, d in data["events"].items()}
            charts.append(
                line_chart(
                    conf,
                    "Confianza media por frame (media móvil de 10)",
                    "confianza",
                    0,
                    1,
                    [(thr.get("upper", 0.65), "superior", "#2f9e57"), (thr.get("lower", 0.4), "inferior", "#d64545")],
                    spans,
                )
            )
            per_source = (run.get("config") or {}).get("alerts", {}).get("low_confidence", {})
            hl = [(v, f"umbral {s}", "#b54708") for s, v in per_source.get("per_source_threshold", {}).items()]
            low_spans = [s for s, a in zip(spans, data["alerts"], strict=True) if a["rule_id"] == "low-confidence-v1"]
            charts.append(
                line_chart(
                    data["low_rate"],
                    "Regla low-confidence-v1: proporción baja en la ventana",
                    "proporción",
                    0,
                    1,
                    hl,
                    low_spans,
                )
            )
            inf = {s: list(zip(d["ts"], d["inference_ms"], strict=True)) for s, d in data["events"].items()}
            charts.append(line_chart(inf, "Tiempo de inferencia por frame", "ms", 0, None))
            det = {s: list(zip(d["ts"], d["n_detections"], strict=True)) for s, d in data["events"].items()}
            charts.append(line_chart(det, "Detecciones por frame", "detecciones", 0, None))
            mpath = Path(run["root_dir"]) / "metrics.json"
            metrics = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else None
        return render(request, "dashboard.html", run=run, facets=facets, charts=charts, data=data, metrics=metrics)

    def _live_sources() -> list[str]:
        return sorted(p.stem for p in app.state.live_dir.glob("*.jpg"))

    @app.get("/live", response_class=HTMLResponse)
    def live(request: Request):
        now = time.time()
        sources = [{"id": s, "age": now - (app.state.live_dir / f"{s}.jpg").stat().st_mtime} for s in _live_sources()]
        return render(request, "live.html", sources=sources)

    @app.get("/live/{source_id}.jpg")
    def live_frame(source_id: str):
        path = app.state.live_dir / f"{source_id}.jpg"
        if source_id not in _live_sources():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/live/{source_id}.mjpg")
    async def live_stream(source_id: str, max_frames: int = 1200):
        if source_id not in _live_sources():
            raise HTTPException(404)
        path = app.state.live_dir / f"{source_id}.jpg"

        async def frames():
            last = None
            for _ in range(max_frames):
                try:
                    stat = path.stat()
                    if stat.st_mtime != last:
                        last = stat.st_mtime
                        data = path.read_bytes()
                        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
                except OSError:
                    pass
                await asyncio.sleep(0.25)

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")

    # --- API JSON -----------------------------------------------------------------------
    @app.get("/api/events")
    def api_events(request: Request):
        f = event_filter(request)
        with db() as conn:
            rows, total = q.events(conn, f)
        return {"total": total, "page": f.page, "page_size": q.PAGE_SIZE, "items": rows}

    @app.get("/api/events/{event_id}")
    def api_event(event_id: str):
        with db() as conn:
            ev = q.event(conn, event_id)
        if not ev:
            raise HTTPException(404, "Evento no encontrado")
        return ev

    @app.get("/api/alerts")
    def api_alerts(status: str | None = None, rule_id: str | None = None, source_id: str | None = None):
        with db() as conn:
            return q.alerts(conn, status, rule_id, source_id)

    @app.get("/api/alerts/{alert_id}")
    def api_alert(alert_id: str):
        with db() as conn:
            a = q.alert(conn, alert_id)
        if not a:
            raise HTTPException(404, "Alerta no encontrada")
        return a

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "version": __version__}

    return app
