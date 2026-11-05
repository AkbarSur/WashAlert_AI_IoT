"""Perbandingan empat kelompok pada skenario yang sama (DML perbandingan).

    python -m ml.compare_arms --sessions-dir data/synthetic --split data/manifests/split_syn_hard_v1_v1.json \
        --model models/development/SYNTHETIC_... --allow-synthetic --out reports/arms/syn_hard_v1

Model hanya dinilai pada grup test di split, agar tidak memakai siklus yang dipakai melatihnya.
Hasil dari data sintetis hanya menguji perangkat lunak dan tidak menjadi bukti performa nyata.
"""

import argparse
import json
from pathlib import Path

from ml.replay import evaluate_legacy_cycle, evaluate_new_cycle, true_cycle_bounds
from ml.validate_dataset import validate_session
from nodes.detector_service.inference import ActivityModel

ARMS = ("1_legacy_fsm", "2_new_fsm_rule", "3_hybrid", "4_ml_only")


def session_folder(root: Path, group: str) -> Path:
    for name in (group, f"SYNTHETIC_{group}"):
        if (root / name).is_dir():
            return root / name
    raise FileNotFoundError(group)


def summarize(rows: list[dict]) -> dict:
    delays = [r["delay_s"] for r in rows if r["delay_s"] is not None]
    return {"cycles": len(rows), "detected": sum(r["detected"] for r in rows), "missed": sum(r["missed"] for r in rows),
            "false_alerts": sum(r["false_alerts"] for r in rows), "corrections": sum(r.get("corrections", 0) for r in rows),
            "delay_s_mean": round(sum(delays) / len(delays), 1) if delays else None,
            "delay_s_max": max(delays) if delays else None}


def compare(root: Path, groups: list[str], model) -> dict:
    per_arm = {}
    for arm in ARMS:
        rows = []
        for group in groups:
            folder = session_folder(root, group)
            report = validate_session(folder)
            if true_cycle_bounds(report.labels)[0] is None:
                continue
            rows.append(evaluate_legacy_cycle(folder) if arm == ARMS[0] else evaluate_new_cycle(folder, arm, model))
        per_arm[arm] = {"summary": summarize(rows), "cycles": rows}
    return per_arm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-dir", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    split = json.loads(args.split.read_text())
    model = ActivityModel.load(args.model, args.allow_synthetic)
    result = {"data_kind": model.data_kind, "model_version": model.version, "split": str(args.split),
              "evaluation_ready": split.get("evaluation_ready"), "test_groups": split["test"],
              "arms": compare(args.sessions_dir, split["test"], model)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "arms.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v["summary"] for k, v in result["arms"].items()}, indent=1))
    print(json.dumps({k: [{x: c.get(x) for x in ("session_id", "delay_s", "false_alerts", "sources")} for c in v["cycles"]] for k, v in result["arms"].items()}))


if __name__ == "__main__":
    main()
