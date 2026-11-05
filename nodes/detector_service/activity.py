"""Sumber aktivitas untuk FSM (FR pemisahan aktivitas dan keputusan, fallback, smoothing).

Modul ini hanya menjawab "mesin sedang apa". Keputusan DONE, alert, dan konfirmasi tetap di rules.py.
Tanpa MQTT, dan aman diimpor tanpa scikit-learn.
"""

import time
from collections import Counter, deque
from dataclasses import dataclass

from nodes.detector_service.inference import try_load
from shared.features import BASE_F2, QUALITY_FIELDS, AggregateBuffer, WindowConfig, window_usable

IDLE, WASHING, SPIN, UNKNOWN = "IDLE", "WASHING", "SPIN", "UNKNOWN"
MAX_PREDICTION_ERRORS = 5
RUNTIME_MODES = ("RULE_ONLY", "HYBRID", "ML_ONLY")


@dataclass(frozen=True)
class ActivityEstimate:
    activity: str
    source: str                       # rule | model | rule_low_probability | rule_fallback | none
    probability: float | None = None  # probabilitas model, belum tentu terkalibrasi
    reason: str | None = None
    classified_at_ms: int | None = None


def sensor_unreliable(reading) -> str | None:
    """Data yang rusak bukan bukti mesin diam, baik bagi aturan maupun model. v1 tidak punya info ini."""
    extra = reading.extra
    if not extra:
        return None
    if extra["sensor_fault"]:
        return "sensor_fault"
    return None if window_usable(extra) else "stale_sensor"


class RuleActivitySource:
    """Ambang lama. Bukan ML. Punya hysteresis sehingga butuh state FSM saat ini."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.raw = deque(maxlen=3)
        self.rotation = deque(maxlen=max(1, cfg.spin_windows))

    def reset(self):
        self.raw.clear()
        self.rotation.clear()

    def estimate(self, reading, now_ms: int, state: str, avg_rms: float) -> ActivityEstimate:
        cfg = self.cfg
        unreliable = sensor_unreliable(reading)
        if unreliable:
            return ActivityEstimate(UNKNOWN, "none", reason=unreliable, classified_at_ms=now_ms)
        self.raw.append(reading.motion_rms)
        if state in ("IDLE", "DONE"):
            # Dua dari tiga jendela mentah harus aktif, agar satu senggolan tidak terbawa moving average.
            sustained = sum(v >= cfg.wash_threshold for v in self.raw) >= 2
            return ActivityEstimate(WASHING if avg_rms >= cfg.wash_threshold and sustained else IDLE, "rule", classified_at_ms=now_ms)
        if avg_rms < cfg.still_threshold:
            self.rotation.clear()
            return ActivityEstimate(IDLE, "rule", classified_at_ms=now_ms)
        self.rotation.append(reading.rotation_rad)
        spinning = avg_rms >= cfg.spin_threshold or (len(self.rotation) >= cfg.spin_windows and
                                                     all(v >= cfg.spin_rotation for v in self.rotation))
        return ActivityEstimate(SPIN if spinning else WASHING, "rule", classified_at_ms=now_ms)


class ModelActivitySource:
    """Model terlatih. allow_fallback=True untuk HYBRID, False untuk ML_ONLY.

    ML_ONLY tidak memakai aturan saat prediksi tidak tersedia. Aktivitas menjadi UNKNOWN dan FSM menahan timer.
    Jika model gagal berulang, kedua mode pindah ke aturan dan status melaporkan RULE_ONLY.
    """

    def __init__(self, model, cfg, allow_fallback: bool = True):
        self.model = model
        self.allow_fallback = allow_fallback
        self.rule = RuleActivitySource(cfg)
        window = model.metadata.get("window", {})
        self.window_config = WindowConfig(window.get("aggregate_s", 30.0), window.get("min_windows", 3), window.get("min_coverage_s", 20.0))
        self.buffer = AggregateBuffer(self.window_config)
        self.votes = deque(maxlen=int(model.metadata.get("smoothing_n", 5)))
        self.errors = 0
        self.disabled_reason = None
        self.last_latency_ms = None

    def reset(self):
        self.rule.reset()
        self.buffer = AggregateBuffer(self.window_config)
        self.votes.clear()

    def _predict(self, reading, now_ms):
        """(prediksi, alasan gagal)."""
        if self.disabled_reason:
            return None, self.disabled_reason
        extra = reading.extra
        if not extra:
            return None, "missing_features"
        window = {"motion_rms": reading.motion_rms, "rotation_rad": reading.rotation_rad,
                  **{k: extra[k] for k in QUALITY_FIELDS + BASE_F2}}
        self.buffer.add(now_ms, window)
        features = self.buffer.aggregate()
        if features is None:
            return None, "incomplete_window"
        started = time.perf_counter()
        prediction = self.model.predict(features)
        self.last_latency_ms = round((time.perf_counter() - started) * 1000, 3)
        if prediction.ok and prediction.activity not in (IDLE, WASHING, SPIN):
            prediction, reason = None, "unexpected_label"
        elif not prediction.ok and str(prediction.reason).startswith("prediction_error"):
            reason = "prediction_error"
        else:
            self.errors = 0
            return prediction, None if prediction.ok else prediction.reason
        self.errors += 1
        if self.errors >= MAX_PREDICTION_ERRORS:
            self.disabled_reason = reason
        return prediction, reason

    def _smooth(self, raw: str) -> str:
        self.votes.append(raw)
        counts = Counter(self.votes)
        top = max(counts.values())
        return raw if counts[raw] == top else next(a for a in reversed(self.votes) if counts[a] == top)

    def estimate(self, reading, now_ms: int, state: str, avg_rms: float) -> ActivityEstimate:
        rule = self.rule.estimate(reading, now_ms, state, avg_rms)
        if rule.activity == UNKNOWN:
            self.votes.clear()
            return rule
        prediction, failure = self._predict(reading, now_ms)
        ok = failure is None and prediction is not None and prediction.ok
        probability = prediction.max_probability if ok else None
        if self.disabled_reason:
            raw, source, reason = rule.activity, "rule_fallback", self.disabled_reason
        elif not self.allow_fallback:
            if not ok:
                return ActivityEstimate(UNKNOWN, "none", None, failure, now_ms)
            raw, source, reason = prediction.activity, "model", prediction.reason
        elif ok and not prediction.use_fallback:
            raw, source, reason = prediction.activity, "model", None
        elif ok and prediction.low_probability:
            raw, source, reason = rule.activity, "rule_low_probability", "low_probability"
        else:
            raw, source, reason = rule.activity, "rule_fallback", failure or prediction.reason
        return ActivityEstimate(self._smooth(raw), source, probability, reason, now_ms)


def make_activity_source(mode: str, model_path: str | None, cfg, allow_synthetic: bool = False) -> tuple:
    """(sumber, info). Kegagalan model tidak pernah menghentikan detector, tetapi selalu terlihat."""
    if mode not in RUNTIME_MODES:
        raise ValueError(f"DETECTION_MODE tidak dikenal: {mode}. Pilihan: {', '.join(RUNTIME_MODES)}")
    info = {"detection_mode": mode, "effective_mode": "RULE_ONLY", "model_status": "not_configured"}
    if mode == "RULE_ONLY":
        return RuleActivitySource(cfg), info
    if not model_path:
        return RuleActivitySource(cfg), {**info, "model_status": "unavailable", "fallback_reason": "model_missing"}
    model, reason = try_load(model_path, allow_synthetic)
    if model is None:
        return RuleActivitySource(cfg), {**info, "model_status": "unavailable", "fallback_reason": reason}
    return ModelActivitySource(model, cfg, allow_fallback=mode == "HYBRID"), {
        **info, "effective_mode": mode, "model_status": "active", "model_name": model.metadata["model_name"],
        "model_version": model.version, "model_data_kind": model.data_kind,
        "probability_calibrated": bool(model.metadata.get("probability_calibrated", False))}
