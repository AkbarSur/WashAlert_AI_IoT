"""Evaluasi akhir sekali pada test set (FR perintah evaluasi, DML kunci test set).

python -m ml.evaluate --model-dir models/development/<versi>

Model dimuat lewat jalur inference yang sama dengan runtime. Setiap pembukaan test dicatat.
Metrik aktivitas tidak sama dengan keberhasilan notifikasi; metrik siklus dilaporkan terpisah.
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ml import figures, replay
from ml.baselines.rule_activity import rule_activity
from ml.dataset_io import read_json, write_json
from ml.metrics import compute_metrics, longest_false_idle_seconds
from ml.split_dataset import group_of, read_windows, verify_split
from nodes.detector_service.inference import ActivityModel


class EvaluationError(ValueError):
    pass


def log_access(path: Path, row: dict):
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=list(row), lineterminator="\n")
        if new:
            w.writeheader()
        w.writerow(row)


def evaluate(model_dir, processed_root="data/processed", sessions_root=None, reports_root="reports/experiments",
             allow_reevaluation=False, make_figures=True) -> dict:
    model_dir = Path(model_dir)
    meta_path = model_dir / "metadata.json"
    metadata = read_json(meta_path)
    if metadata.get("test_results") and not allow_reevaluation:
        raise EvaluationError("Test set sudah pernah dipakai untuk model ini. Gunakan --allow-reevaluation dan catat alasannya")
    model = ActivityModel.load(model_dir, allow_synthetic=True)
    dataset_dir = Path(processed_root) / metadata["dataset_id"]
    split = read_json(metadata["split_file"])
    verify_split(split, dataset_dir)
    if split["windows_sha256"] != metadata["windows_sha256"]:
        raise EvaluationError("Dataset berbeda dari saat training")
    test_groups = set(split["test"])
    if test_groups & set(metadata["train_groups"] + metadata["validation_groups"]):
        raise EvaluationError("Kebocoran: grup test dipakai saat training")
    rows = [r for r in read_windows(dataset_dir / "windows.csv") if group_of(r) in test_groups]
    if not rows:
        raise EvaluationError("Test set kosong")

    kind = metadata["data_kind"]
    now = datetime.now(timezone.utc).isoformat()
    log_access(Path(reports_root) / "test_access_log.csv", {"time": now, "model_version": model.version, "dataset_id": metadata["dataset_id"],
                                                            "split_version": metadata["split_version"], "reevaluation": bool(metadata.get("test_results"))})
    y = [r["label"] for r in rows]
    predictions = [model.predict({n: float(r[n]) for n in model.feature_names}) for r in rows]
    if not all(p.ok for p in predictions):
        raise EvaluationError(f"Prediksi gagal: {next(p.reason for p in predictions if not p.ok)}")
    pred = [p.activity for p in predictions]
    selected = compute_metrics(y, pred)
    rule = [rule_activity(float(r["motion_rms_mean"]), float(r["rotation_rad_mean"])) for r in rows]
    hybrid = [g if p.use_fallback else p.activity for p, g in zip(predictions, rule)]
    results = {"selected_model": selected, "selected_with_rule_fallback": compute_metrics(y, hybrid),
               "baseline_majority": compute_metrics(y, [metadata["majority_class"]] * len(y)), "baseline_threshold": compute_metrics(y, rule)}

    sessions = {}
    for r in rows:
        sessions.setdefault(r["session_id"], []).append(r)
    per_session, cycles = {}, []
    legacy_pred = []
    root = Path(sessions_root) if sessions_root else None
    for sid, items in sessions.items():
        idx = [i for i, r in enumerate(rows) if r["session_id"] == sid]
        per_session[sid] = {"windows": len(items), "macro_f1": compute_metrics([y[i] for i in idx], [pred[i] for i in idx])["macro_f1"],
                            "longest_active_predicted_idle_s": longest_false_idle_seconds(items, [pred[i] for i in idx])}
        if root:
            series = replay.replay_legacy(root / sid)
            legacy_pred.extend(replay.activity_at(series, [int(r["window_end_ms"]) for r in items]))
            if items[0]["session_type"] == "cycle":
                cycles.append(replay.evaluate_legacy_cycle(root / sid))
    if root:
        ordered_y = [r["label"] for items in sessions.values() for r in items]
        results["baseline_fsm_old_mapped"] = compute_metrics(ordered_y, legacy_pred)

    report = {
        "evaluated_at": now, "model_version": model.version, "data_kind": kind, "dataset_id": metadata["dataset_id"],
        "n_test_windows": len(rows), "test_groups": sorted(test_groups), "results": results, "per_session": per_session,
        "low_probability_rate": sum(p.low_probability for p in predictions) / len(predictions),
        "out_of_range_rate": sum(bool(p.out_of_range_features) for p in predictions) / len(predictions),
        "end_to_end_arm1_legacy": cycles,
        "end_to_end_pending": "Arm 2, 3, 4 menunggu FSM baru dan integrasi Phase 6",
        "warning": None if kind == "real" else "DATA SINTETIS. Bukan bukti performa pada mesin cuci.",
    }
    exp_dir = Path(reports_root) / metadata["experiment_id"]
    (exp_dir / "figures").mkdir(parents=True, exist_ok=True)
    write_json(exp_dir / "test_report.json", {**report, "results": {k: {a: b for a, b in v.items() if a != "classification_report"} for k, v in results.items()}})
    (exp_dir / "test_classification_report.txt").write_text(("DATA SINTETIS\n" if kind != "real" else "") + selected["classification_report"], encoding="utf-8")
    if make_figures:
        figures.confusion(selected, f"Confusion matrix test: {metadata['algorithm']}/{metadata['feature_set']}", kind, exp_dir / "figures" / "confusion_test.png")
        cycle_ids = [s for s, items in sessions.items() if items[0]["session_type"] == "cycle"] or list(sessions)
        first = cycle_ids[0]
        idx = [i for i, r in enumerate(rows) if r["session_id"] == first]
        figures.timeline([rows[i] for i in idx], [pred[i] for i in idx], f"Prediksi aktivitas pada satu siklus test ({first})", kind, exp_dir / "figures" / "timeline_test.png")

    metadata["test_results"] = {k: {a: b for a, b in v.items() if a != "classification_report"} for k, v in {"selected_model": selected}.items()} | {"evaluated_at": now}
    claims = metadata["status_claims"]
    claims["D_validated_on_heldout_real"] = kind == "real" and bool(split["evaluation_ready"])
    write_json(meta_path, metadata)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluasi akhir pada test set")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--processed-root", default="data/processed")
    parser.add_argument("--sessions-root")
    parser.add_argument("--reports-root", default="reports/experiments")
    parser.add_argument("--allow-reevaluation", action="store_true")
    args = parser.parse_args(argv)
    try:
        sessions = args.sessions_root
        if not sessions:
            candidate = Path("data") / read_json(Path(args.model_dir) / "metadata.json")["data_kind"]
            sessions = str(candidate) if candidate.exists() else None
        report = evaluate(args.model_dir, args.processed_root, sessions, args.reports_root, args.allow_reevaluation)
    except (ValueError, OSError) as exc:
        print(f"[EVALUASI] Ditolak: {exc}", file=sys.stderr)
        return 2
    if report["warning"]:
        print(f"[EVALUASI] {report['warning']}")
    print(json.dumps({k: round(v["macro_f1"], 4) for k, v in report["results"].items()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
