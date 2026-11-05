"""Contoh pemakaian inference pada satu baris windows.csv atau file JSON fitur.

python -m ml.predict --model-dir models/development/<versi> --windows data/processed/<id>/windows.csv --row 0
"""

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from ml.split_dataset import read_windows
from nodes.detector_service.inference import ActivityModel, ModelLoadError
from shared.features import ALL_FEATURE_COLUMNS


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prediksi aktivitas")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--windows", type=Path)
    parser.add_argument("--row", type=int, default=0)
    parser.add_argument("--features-json", type=Path)
    parser.add_argument("--allow-synthetic", action="store_true")
    args = parser.parse_args(argv)
    try:
        model = ActivityModel.load(args.model_dir, args.allow_synthetic)
    except ModelLoadError as exc:
        print(f"[PREDIKSI] Model tidak dapat dipakai: {exc}. Fallback: aturan.", file=sys.stderr)
        return 2
    if args.features_json:
        try:
            features = json.loads(args.features_json.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[PREDIKSI] File fitur tidak valid: {exc}", file=sys.stderr)
            return 2
    else:
        row = read_windows(args.windows)[args.row]
        features = {k: float(row[k]) for k in ALL_FEATURE_COLUMNS}
    if model.data_kind != "real":
        print("[PREDIKSI] MODEL SINTETIS: hanya menguji perangkat lunak.")
    print(json.dumps(dataclasses.asdict(model.predict(features)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
