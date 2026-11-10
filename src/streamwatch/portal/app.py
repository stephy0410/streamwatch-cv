"""Portal de monitoreo (FastAPI + Jinja2, renderizado en servidor, sin dependencias de JS).

Vistas obligatorias: consulta de eventos y de alertas, con vínculos hasta la imagen, la
configuración y los eventos que originaron cada alerta. API JSON equivalente en ``/api``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from streamwatch import __version__
from streamwatch.portal import queries as q
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


def _flag(value: str | None) -> bool:
    return value in ("1", "true", "on", "yes")


def create_app(db_path: str = "data/streamwatch.db", live_dir: str = "data/live") -> FastAPI:
    connect(db_path).close()  # crea el esquema si el SQLite aún no existe
    app = FastAPI(title="StreamWatch CV", version=__version__)
    app.state.db_path = db_path
    app.state.live_dir = Path(live_dir)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals.update(STATE_LABELS=STATE_LABELS, RULE_LABELS=RULE_LABELS, version=__version__)
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
        return render(request, "alert.html", a=a)

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
