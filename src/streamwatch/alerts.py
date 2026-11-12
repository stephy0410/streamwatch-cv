"""Motor de reglas de alerta.

Cada regla se evalúa por fuente y deja una *evaluación* con su estado:

- ``ok``            — hay evidencia suficiente y la condición no se cumple
- ``breach``        — hay evidencia suficiente y la condición se cumple
- ``insufficient``  — la ventana no tiene el mínimo de observaciones: **no es normalidad**
- ``no_reference``  — no hay referencia comparable (regla de cambio sostenido): falta, o con
  ``require_same_model`` el evento viene de un modelo distinto al de la referencia (series separadas)
- ``hold``          — con la alerta abierta, el valor ya no cumple la condición pero sigue dentro del
  margen de histéresis (``clear_margin``): ni confirma ni resuelve

Una alerta se abre cuando hay ``persistence`` evaluaciones ``breach`` seguidas, y se resuelve tras
``clear_after`` evaluaciones ``ok`` seguidas. Las evaluaciones ``insufficient`` rompen la racha de
``breach`` pero no cuentan para resolver; ``hold`` rompe la racha de ``ok``. Hay como máximo una
alerta abierta por regla y fuente.
"""

from __future__ import annotations

import statistics
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from streamwatch.config import MonitorConfig
from streamwatch.events import iso

RULES = {
    "low-confidence-v1": {
        "metric": "low_confidence_rate",
        "action": (
            "Revisar las capturas de la ventana: iluminación, oclusión, cámara movida o escena fuera de "
            "dominio. Confirmar con datos etiquetados antes de reentrenar."
        ),
    },
    "confidence-shift-v1": {
        "metric": "mean_score_drop_vs_reference",
        "action": (
            "Comparar con la referencia: ¿cambió la escena (noche, clima), la cámara o el modelo? Si persiste, "
            "recolectar y etiquetar muestras y recalibrar la referencia."
        ),
    },
    "detector-silence-v1": {
        "metric": "empty_frame_share",
        "action": (
            "Abrir las capturas: si la escena tiene objetos y el modelo no los detecta, revisar iluminación, "
            "enfoque u obstrucción de la cámara. Si la escena está realmente vacía, es un cambio de escena y no "
            "un fallo del modelo."
        ),
    },
    "stream-stale-v1": {
        "metric": "seconds_since_last_frame",
        "action": (
            "Verificar la transmisión y la red. El monitor reintenta con backoff y re-resuelve la URL; si no se "
            "recupera, revisar la fuente en la configuración."
        ),
    },
    "model-version-v1": {
        "metric": "model_name_mismatch",
        "action": (
            "Revertir al modelo aprobado (model.expected_name) o aprobar formalmente la nueva versión y "
            "recalibrar la referencia antes de compararla."
        ),
    },
}


@dataclass(frozen=True)
class Observation:
    event_id: str
    source_id: str
    ts: float
    status: str
    scores: tuple[float, ...]
    n_low: int
    model_name: str


@dataclass
class Outcome:
    evaluations: list[dict[str, Any]] = field(default_factory=list)
    opened: list[dict[str, Any]] = field(default_factory=list)
    resolved: list[dict[str, Any]] = field(default_factory=list)

    def extend(self, other: Outcome) -> None:
        self.evaluations += other.evaluations
        self.opened += other.opened
        self.resolved += other.resolved


@dataclass
class _State:
    breach_streak: int = 0
    ok_streak: int = 0
    open_alert: dict[str, Any] | None = None
    counter: int = 0
    last_breach_window: list[str] = field(default_factory=list)


class RuleEngine:
    def __init__(
        self,
        cfg: MonitorConfig,
        run_id: str,
        reference: dict[str, Any] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.cfg = cfg
        self.run_id = run_id
        self.config_ref = cfg.config_ref
        self.reference = reference or {}
        self.clock = clock
        self.lower = cfg.confidence.lower
        a = cfg.alerts
        maxlen = max(a.low_confidence.window_frames, a.confidence_shift.window_frames, a.detector_silence.window_frames)
        self.windows: dict[str, deque[Observation]] = {}
        self._maxlen = maxlen
        self.states: dict[tuple[str, str], _State] = {}
        self.last_event: dict[str, str] = {}

    # --- utilidades ---------------------------------------------------------------------
    def _state(self, rule_id: str, source_id: str) -> _State:
        return self.states.setdefault((rule_id, source_id), _State())

    def open_alerts(self) -> list[dict[str, Any]]:
        return [s.open_alert for s in self.states.values() if s.open_alert]

    def _evaluation(self, rule_id, source_id, ts, state, value, threshold, extra=None) -> dict[str, Any]:
        ev = {
            "run_id": self.run_id,
            "rule_id": rule_id,
            "source_id": source_id,
            "timestamp": iso(ts),
            "state": state,
            "value": None if value is None else round(value, 4),
            "threshold": threshold,
            "config_ref": self.config_ref,
        }
        if extra:
            ev.update(extra)
        return ev

    def _transition(
        self,
        rule_id: str,
        source_id: str,
        ts: float,
        state: str,
        value: float | None,
        threshold: float | None,
        persistence: int,
        clear_after: int,
        severity: str,
        reason: str,
        window: dict[str, Any],
    ) -> Outcome:
        st = self._state(rule_id, source_id)
        out = Outcome()
        if state == "breach":
            st.breach_streak += 1
            st.ok_streak = 0
        elif state == "ok":
            st.ok_streak += 1
            st.breach_streak = 0
        elif state == "hold":  # dentro del margen de histéresis: no cuenta para resolver
            st.breach_streak = 0
            st.ok_streak = 0
        else:  # insufficient / no_reference: no confirma ni descarta
            st.breach_streak = 0
        out.evaluations.append(
            self._evaluation(
                rule_id,
                source_id,
                ts,
                state,
                value,
                threshold,
                {"breach_streak": st.breach_streak, "ok_streak": st.ok_streak, "alert_open": bool(st.open_alert)},
            )
        )
        if st.open_alert is None and state == "breach" and st.breach_streak >= persistence:
            st.counter += 1
            short = rule_id.removesuffix("-v1")
            alert = {
                "alert_id": f"alt-{self.run_id}-{short}-{source_id}-{st.counter:03d}",
                "run_id": self.run_id,
                "rule_id": rule_id,
                "source_id": source_id,
                "config_ref": self.config_ref,
                "status": "open",
                "severity": severity,
                "opened_at": iso(ts),
                "resolved_at": None,
                "metric": RULES[rule_id]["metric"],
                "value": None if value is None else round(value, 4),
                "threshold": threshold,
                "persistence": persistence,
                "reason": reason,
                "suggested_action": RULES[rule_id]["action"],
                "window": window,
                "event_ids": list(window.get("event_ids", [])),
                "trigger_event_id": window.get("end_event"),
                "trigger_image_ref": None,
            }
            alert["window"] = {k: v for k, v in window.items() if k != "event_ids"}
            st.open_alert = alert
            out.opened.append(alert)
        elif st.open_alert is not None and state == "ok" and st.ok_streak >= clear_after:
            alert = {
                **st.open_alert,
                "status": "resolved",
                "resolved_at": iso(ts),
                "resolution": f"{clear_after} evaluaciones seguidas dentro de lo normal (último valor {value:.3f})"
                if value is not None
                else "condición restablecida",
            }
            st.open_alert = None
            out.resolved.append(alert)
        return out

    def _classify(self, rule_id: str, source_id: str, value: float, threshold: float, margin: float) -> str:
        """``breach`` si cumple la condición; con la alerta abierta, ``ok`` solo por debajo de
        ``threshold − margin`` y ``hold`` en la banda intermedia."""
        if value >= threshold:
            return "breach"
        if margin and self._state(rule_id, source_id).open_alert is not None and value >= threshold - margin:
            return "hold"
        return "ok"

    # --- reglas sobre observaciones -----------------------------------------------------
    def observe(self, obs: Observation) -> Outcome:
        win = self.windows.setdefault(obs.source_id, deque(maxlen=self._maxlen))
        self.last_event[obs.source_id] = obs.event_id
        out = Outcome()
        if obs.status == "ok":
            win.append(obs)
        out.extend(self._low_confidence(obs, win))
        out.extend(self._confidence_shift(obs, win))
        out.extend(self._detector_silence(obs, win))
        out.extend(self._model_version(obs))
        return out

    @staticmethod
    def _window(win: deque[Observation], n: int) -> list[Observation]:
        return list(win)[-n:]

    @staticmethod
    def _window_info(items: list[Observation], scored: int) -> dict[str, Any]:
        return {
            "frames": len(items),
            "scored_detections": scored,
            "start_event": items[0].event_id if items else None,
            "end_event": items[-1].event_id if items else None,
            "start_ts": iso(items[0].ts) if items else None,
            "end_ts": iso(items[-1].ts) if items else None,
            "event_ids": [o.event_id for o in items],
        }

    def _low_confidence(self, obs: Observation, win: deque[Observation]) -> Outcome:
        rule = self.cfg.alerts.low_confidence
        items = self._window(win, rule.window_frames)
        scored = sum(len(o.scores) for o in items)
        low = sum(o.n_low for o in items)
        threshold = rule.per_source_threshold.get(obs.source_id, rule.rate_threshold)
        if len(items) < rule.window_frames or scored < rule.min_detections:
            state, value = "insufficient", (low / scored if scored else None)
        else:
            value = low / scored
            state = self._classify("low-confidence-v1", obs.source_id, value, threshold, rule.clear_margin)
        reason = (
            f"{low} de {scored} detecciones ({(value or 0):.0%}) bajo el umbral inferior {self.lower} en los "
            f"últimos {len(items)} frames de {obs.source_id}; umbral de la regla {threshold:.0%}, "
            f"persistencia {rule.persistence} evaluaciones."
        )
        return self._transition(
            "low-confidence-v1",
            obs.source_id,
            obs.ts,
            state,
            value,
            threshold,
            rule.persistence,
            rule.clear_after,
            rule.severity,
            reason,
            self._window_info(items, scored),
        )

    def _confidence_shift(self, obs: Observation, win: deque[Observation]) -> Outcome:
        rule = self.cfg.alerts.confidence_shift
        items = self._window(win, rule.window_frames)
        scores = [s for o in items for s in o.scores]
        ref = self.reference.get("sources", {}).get(obs.source_id, {}).get("mean_score")
        ref_model = (self.reference.get("model_ref") or "").split("@")[0] or None
        other_model = rule.require_same_model and ref_model is not None and obs.model_name != ref_model
        drop = None
        if ref is None or other_model:
            state = "no_reference"
        elif len(items) < rule.window_frames or len(scores) < rule.min_detections:
            state = "insufficient"
        else:
            mean = statistics.fmean(scores)
            drop = ref - mean
            state = self._classify("confidence-shift-v1", obs.source_id, drop, rule.tolerance, rule.clear_margin)
        mean_txt = f"{ref - drop:.3f}" if drop is not None else "n/d"
        reason = (
            f"Confianza media {mean_txt} en {len(scores)} detecciones de los últimos {len(items)} frames vs "
            f"referencia {ref if ref is None else round(ref, 3)} (caída {(drop or 0):.3f} ≥ tolerancia "
            f"{rule.tolerance}) sostenida {rule.persistence} evaluaciones. Posible cambio de escena, cámara o "
            "modelo; la confianza no confirma por sí sola pérdida de calidad."
        )
        if other_model:
            reason = (
                f"Sin referencia comparable: el evento viene de '{obs.model_name}' y la referencia es de "
                f"'{ref_model}'. Las series de modelos distintos no se comparan; el cambio de versión lo reporta "
                "model-version-v1."
            )
        info = self._window_info(items, len(scores))
        info["reference_mean"] = ref
        info["reference_model"] = ref_model
        return self._transition(
            "confidence-shift-v1",
            obs.source_id,
            obs.ts,
            state,
            drop,
            rule.tolerance,
            rule.persistence,
            rule.clear_after,
            rule.severity,
            reason,
            info,
        )

    def _detector_silence(self, obs: Observation, win: deque[Observation]) -> Outcome:
        rule = self.cfg.alerts.detector_silence
        if not rule.enabled:
            return Outcome()
        items = self._window(win, rule.window_frames)
        empty = sum(not o.scores for o in items)
        threshold = rule.per_source_threshold.get(obs.source_id, rule.empty_share_threshold)
        if len(items) < rule.window_frames:
            state, value = "insufficient", (empty / len(items) if items else None)
        else:
            value = empty / len(items)
            state = self._classify("detector-silence-v1", obs.source_id, value, threshold, rule.clear_margin)
        reason = (
            f"{empty} de {len(items)} frames de {obs.source_id} sin ninguna detección "
            f"({(value or 0):.0%}, umbral {threshold:.0%}, persistencia {rule.persistence}). El modelo dejó de "
            "detectar: puede ser poca luz, cámara obstruida o una escena realmente vacía."
        )
        info = self._window_info(items, sum(len(o.scores) for o in items))
        info["empty_frames"] = empty
        return self._transition(
            "detector-silence-v1",
            obs.source_id,
            obs.ts,
            state,
            value,
            threshold,
            rule.persistence,
            rule.clear_after,
            rule.severity,
            reason,
            info,
        )

    def _model_version(self, obs: Observation) -> Outcome:
        rule = self.cfg.alerts.model_version
        expected = self.cfg.model.expected_name
        if not rule.enabled or not expected:
            return Outcome()
        state = "breach" if obs.model_name != expected else "ok"
        reason = f"El evento reporta el modelo '{obs.model_name}' y la versión aprobada es '{expected}'."
        info = {
            "frames": 1,
            "start_event": obs.event_id,
            "end_event": obs.event_id,
            "start_ts": iso(obs.ts),
            "end_ts": iso(obs.ts),
            "event_ids": [obs.event_id],
            "expected_model": expected,
            "reported_model": obs.model_name,
        }
        return self._transition(
            "model-version-v1",
            obs.source_id,
            obs.ts,
            state,
            float(state == "breach"),
            0.0,
            1,
            1,
            rule.severity,
            reason,
            info,
        )

    # --- regla temporal (se evalúa en cada vuelta, haya o no frame) ---------------------
    def tick(self, source_id: str, now: float, last_frame_at: float | None, started_at: float) -> Outcome:
        rule = self.cfg.alerts.stream_stale
        age = now - (last_frame_at if last_frame_at is not None else started_at)
        state = "breach" if age > rule.max_age_s else "ok"
        last = self.last_event.get(source_id)
        reason = (
            f"Sin frames nuevos de {source_id} desde hace {age:.1f} s (máximo {rule.max_age_s} s). "
            f"Último evento: {last or 'ninguno'}."
        )
        info = {
            "frames": 0,
            "start_event": last,
            "end_event": last,
            "start_ts": iso(last_frame_at) if last_frame_at else None,
            "end_ts": iso(now),
            "event_ids": [last] if last else [],
        }
        return self._transition(
            "stream-stale-v1", source_id, now, state, age, rule.max_age_s, 1, 1, rule.severity, reason, info
        )
