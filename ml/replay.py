"""Pemutaran ulang rekaman melalui FSM lama, tanpa broker (FR pemutaran ulang, arm 1).

Arm 1 FSM lama beku. Arm 2 FSM baru + aturan. Arm 3 HYBRID. Arm 4 model tanpa fallback (offline saja).
Waktu berasal dari rekaman, bukan jam sistem, sehingga hasilnya deterministik.
"""

import bisect
from collections import Counter
from pathlib import Path

from ml.baselines.legacy_rules import Config, WasherDetector
from ml.build_dataset import edge_windows
from ml.validate_dataset import validate_session
from nodes.detector_service.activity import ModelActivitySource, RuleActivitySource
from nodes.detector_service.inference import ActivityModel
from nodes.detector_service import rules as new_rules
from shared.features import telemetry_extra
from shared.messages import Telemetry

REAL_CONFIG = Config(start_s=60, done_s=120, remind_s=300)
# Nilai usulan FSM baru pada mode real. Belum divalidasi dengan data nyata.
NEW_CONFIG = new_rules.Config(start_s=60, done_s=120, remind_s=300, min_run_s=600, done_nospin_s=240, ack_windows=2, spin_windows=3)
COMPLETION_KINDS = ("completed_after_spin", "stopped_without_spin")


def replay_legacy(session_dir: Path, config: Config = REAL_CONFIG) -> list[dict]:
    report = validate_session(session_dir)
    if report.rejected:
        raise ValueError(f"Sesi ditolak validator: {session_dir}")
    detector = WasherDetector(config)
    out = []
    for seq, (_, end_ms, w) in enumerate(edge_windows(report.rows, int(report.meta["samples_per_window"]),
                                                      report.median_dt, Counter())):
        msg = Telemetry("edge1", "replay", seq, end_ms, w["motion_rms"], w["rotation_rad"])
        d = detector.accept(msg, now_ms=end_ms)
        out.append({"t_ms": end_ms, "status": d.status, "alert": d.alert})
    return out


def make_new_detector(arm: str, model: ActivityModel | None, config=NEW_CONFIG):
    if arm == "2_new_fsm_rule":
        source = RuleActivitySource(config)
    elif arm == "3_hybrid":
        source = ModelActivitySource(model, config, allow_fallback=True)
    elif arm == "4_ml_only":
        source = ModelActivitySource(model, config, allow_fallback=False)
    else:
        raise ValueError(arm)
    return new_rules.WasherDetector(config, activity_source=source)


def replay_new(session_dir: Path, arm: str, model: ActivityModel | None = None, config=NEW_CONFIG) -> list[dict]:
    """Memutar rekaman lewat rules.py produksi. Tick dipanggil sekali per jendela."""
    report = validate_session(session_dir)
    if report.rejected:
        raise ValueError(f"Sesi ditolak validator: {session_dir}")
    detector = make_new_detector(arm, model, config)
    out = []
    for seq, (_, end_ms, w) in enumerate(edge_windows(report.rows, int(report.meta["samples_per_window"]),
                                                      report.median_dt, Counter())):
        msg = Telemetry("edge1", "replay", seq, end_ms, w["motion_rms"], w["rotation_rad"],
                        {"schema_version": 2, **telemetry_extra(w)})
        d = detector.accept(msg, now_ms=end_ms)
        out.append({"t_ms": end_ms, "status": d.status, "alert": d.alert, "kind": d.alert_kind, "is_reminder": d.is_reminder,
                    "activity": d.activity, "source": d.activity_source})
    return out


def evaluate_new_cycle(session_dir: Path, arm: str, model: ActivityModel | None = None, config=NEW_CONFIG) -> dict:
    report = validate_session(session_dir)
    offset = int(report.meta.get("clock_offset_ms") or 0)
    _, end = true_cycle_bounds(report.labels, offset)
    series = replay_new(session_dir, arm, model, config)
    alerts = [s for s in series if s["alert"] and s["kind"] in COMPLETION_KINDS]
    return {"session_id": report.session_id, "arm": arm, "corrections": sum(s["kind"] == "correction" for s in series),
            "sources": dict(Counter(s["source"] for s in series if s["source"])),
            **completion_metrics([s["t_ms"] for s in alerts], end)}


def map_status(status: str) -> str:
    """Pemetaan FSM ke aktivitas. DONE berarti mesin dianggap diam."""
    return {"WASHING": "WASHING", "SPIN": "SPIN"}.get(status, "IDLE")


def activity_at(series: list[dict], times_ms: list[int]) -> list[str]:
    ticks = [s["t_ms"] for s in series]
    out = []
    for t in times_ms:
        i = bisect.bisect_right(ticks, t) - 1
        out.append(map_status(series[i]["status"]) if i >= 0 else "IDLE")
    return out


def true_cycle_bounds(labels: list[dict], offset_ms: int = 0) -> tuple:
    """(awal aktif pertama, akhir aktif terakhir) menurut label observasi."""
    active = [l for l in labels if l["label"] in ("WASHING", "SPIN")]
    if not active:
        return None, None
    return min(l["start_ms"] for l in active) + offset_ms, max(l["end_ms"] for l in active) + offset_ms


def completion_metrics(alert_times_ms: list[int], true_end_ms: int) -> dict:
    """Metrik tingkat siklus dari waktu alert. Alert sebelum mesin benar-benar selesai adalah palsu."""
    false_alerts = sum(t < true_end_ms for t in alert_times_ms)
    after = [t for t in alert_times_ms if t >= true_end_ms]
    return {"false_alerts": false_alerts, "detected": bool(after), "missed": not after,
            "delay_s": round((after[0] - true_end_ms) / 1000, 1) if after else None}


def evaluate_legacy_cycle(session_dir: Path, config: Config = REAL_CONFIG) -> dict:
    report = validate_session(session_dir)
    offset = int(report.meta.get("clock_offset_ms") or 0)
    _, end = true_cycle_bounds(report.labels, offset)
    series = replay_legacy(session_dir, config)
    return {"session_id": report.session_id, "arm": "1_legacy_fsm",
            **completion_metrics([s["t_ms"] for s in series if s["alert"]], end)}


def pause_analysis(session_dirs: list[Path]) -> dict:
    """Jeda IDLE di dalam siklus, untuk menetapkan CUCI_DONE_S. Hanya beri data pengembangan."""
    per_cycle, longest = {}, 0.0
    for folder in session_dirs:
        report = validate_session(folder)
        labels = sorted(report.labels, key=lambda l: l["start_ms"])
        first, last = true_cycle_bounds(labels)
        if first is None:
            continue
        pauses = [(l["end_ms"] - l["start_ms"]) / 1000 for l in labels
                  if l["label"] == "IDLE" and first <= l["start_ms"] and l["end_ms"] <= last]
        per_cycle[report.session_id] = {"pauses_s": [round(p, 1) for p in pauses], "longest_s": round(max(pauses, default=0.0), 1)}
        longest = max(longest, max(pauses, default=0.0))
    return {"per_cycle": per_cycle, "longest_pause_s": round(longest, 1)}
