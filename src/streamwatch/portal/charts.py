"""Gráficas de líneas en SVG generadas en el servidor (sin JavaScript ni CDN)."""

from __future__ import annotations

from datetime import datetime
from html import escape

PALETTE = ["#13806b", "#d9930d", "#3b6fd4", "#a54fc2"]


def _t(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _segments(data: list[tuple[str, float | None]]) -> list[list[tuple[str, float]]]:
    """Parte la serie en tramos contiguos sin ``None``."""
    segs: list[list[tuple[str, float]]] = [[]]
    for ts, v in data:
        if v is None:
            if segs[-1]:
                segs.append([])
        else:
            segs[-1].append((ts, v))
    return [seg for seg in segs if seg]


def line_chart(
    series: dict[str, list[tuple[str, float | None]]],
    title: str,
    y_label: str = "",
    y_min: float | None = 0.0,
    y_max: float | None = None,
    hlines: list[tuple[float, str, str]] | None = None,
    spans: list[tuple[str, str | None, str]] | None = None,
    width: int = 640,
    height: int = 220,
) -> str:
    """``series``: nombre → [(timestamp ISO, valor)]. ``hlines``: (y, etiqueta, color).
    ``spans``: (inicio ISO, fin ISO o None, etiqueta) sombreados (p. ej. alertas abiertas)."""
    pad_l, pad_r, pad_t, pad_b = 48, 12, 28, 26
    pts = [(_t(ts), v) for s in series.values() for ts, v in s if v is not None]
    if not pts:
        return f'<svg viewBox="0 0 {width} {height}" class="chart"><text x="{width / 2}" y="{height / 2}" text-anchor="middle" fill="#8a96a3">{escape(title)}: sin datos</text></svg>'
    t0, t1 = min(p[0] for p in pts), max(p[0] for p in pts)
    t1 = t1 if t1 > t0 else t0 + 1
    vals = [p[1] for p in pts] + [h[0] for h in hlines or []]
    lo = min(vals) if y_min is None else y_min
    hi = max(vals) if y_max is None else y_max
    hi = hi if hi > lo else lo + 1
    w, h = width - pad_l - pad_r, height - pad_t - pad_b

    def x(t: float) -> float:
        return pad_l + (t - t0) / (t1 - t0) * w

    def y(v: float) -> float:
        return pad_t + h - (v - lo) / (hi - lo) * h

    out = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label="{escape(title)}">']
    out.append(f'<text x="{pad_l}" y="16" font-size="13" font-weight="700" fill="#1d2733">{escape(title)}</text>')
    for start, end, label in spans or []:
        xs = x(max(_t(start), t0))
        xe = x(min(_t(end), t1)) if end else x(t1)
        if xe > xs:
            out.append(
                f'<rect x="{xs:.1f}" y="{pad_t}" width="{xe - xs:.1f}" height="{h}" fill="#fde4e4" opacity=".7"><title>{escape(label)}</title></rect>'
            )
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        out.append(f'<line x1="{pad_l}" x2="{pad_l + w}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#eef1f5"/>')
        out.append(
            f'<text x="{pad_l - 6}" y="{y(v) + 4:.1f}" font-size="10" text-anchor="end" fill="#5e6b7a">{v:.2f}</text>'
        )
    for v, label, color in hlines or []:
        out.append(
            f'<line x1="{pad_l}" x2="{pad_l + w}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{color}" stroke-dasharray="5 4"/>'
        )
        out.append(
            f'<text x="{pad_l + w - 4}" y="{y(v) - 4:.1f}" font-size="10" text-anchor="end" fill="{color}">{escape(label)}</text>'
        )
    # Orden estable: la misma fuente conserva su color en todas las corridas.
    for i, (name, data) in enumerate(sorted(series.items())):
        color = PALETTE[i % len(PALETTE)]
        # Un valor None corta la línea: un hueco (p. ej. evidencia insuficiente) no se interpola.
        for seg in _segments(data):
            path = " ".join(f"{x(_t(ts)):.1f},{y(v):.1f}" for ts, v in seg)
            out.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="1.8"/>')
        out.append(
            f'<text x="{pad_l + 8 + i * 150}" y="{height - 6}" font-size="11" fill="{color}">■ {escape(name)}</text>'
        )
    t0s = datetime.fromtimestamp(t0).strftime("%H:%M:%S")
    t1s = datetime.fromtimestamp(t1).strftime("%H:%M:%S")
    out.append(
        f'<text x="{pad_l + w}" y="{height - 6}" font-size="10" text-anchor="end" fill="#5e6b7a">{t0s} → {t1s} (hora local)</text>'
    )
    if y_label:
        out.append(
            f'<text x="12" y="{pad_t + h / 2}" font-size="10" fill="#5e6b7a" transform="rotate(-90 12 {pad_t + h / 2})" text-anchor="middle">{escape(y_label)}</text>'
        )
    out.append("</svg>")
    return "".join(out)
