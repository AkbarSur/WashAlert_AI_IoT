"""Membangun dataset fitur dari sesi tervalidasi (FR ekspor dataset, DML zona transisi).

python -m ml.build_dataset --root data/synthetic --dataset-id syn_v1

Fitur dihitung oleh shared/features.py, modul yang sama dengan edge dan inference.
"""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

from ml.dataset_io import (DATA_KINDS, RAW_SCHEMA_VERSION, TRAINING_LABELS, sha256_file, write_json)
from ml.validate_dataset import GAP_FACTOR, list_sessions, validate_session
from shared.features import (ALL_FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION, AggregateBuffer, InvalidWindow,
                             WindowConfig, compute_window_features, window_usable)
from shared.processing import SensorSample

ID_COLUMNS = ("dataset_id", "session_id", "session_type", "cycle_id", "machine_id", "device_id", "data_kind")
QUALITY_COLUMNS = ("window_start_ms", "window_end_ms", "n_edge_windows", "coverage_s", "median_hz", "stale_ratio")
WINDOW_COLUMNS = ID_COLUMNS + QUALITY_COLUMNS + ALL_FEATURE_COLUMNS + ("label",)
RAW_LABELED_COLUMNS = ("session_id", "device_id", "machine_id", "seq", "t_epoch_ms", "dt_s", "label",
                       "ax", "ay", "az", "gx", "gy", "gz", "accel_fresh", "gyro_fresh", "valid")
TRANSITION_GUARD_S = 10.0  # diusulkan


class DatasetError(ValueError):
    pass


def label_at(labels: list[dict], offset_ms: int, t_ms: int) -> str | None:
    for item in labels:
        if item["start_ms"] + offset_ms <= t_ms < item["end_ms"] + offset_ms:
            return item["label"]
    return None


def boundaries(labels: list[dict], offset_ms: int) -> list[int]:
    """Waktu perubahan label, termasuk awal dan akhir daerah berlabel."""
    points = set()
    ordered = sorted(labels, key=lambda r: r["start_ms"])
    for i, item in enumerate(ordered):
        same_prev = i > 0 and ordered[i - 1]["end_ms"] == item["start_ms"] and ordered[i - 1]["label"] == item["label"]
        same_next = i + 1 < len(ordered) and ordered[i + 1]["start_ms"] == item["end_ms"] and ordered[i + 1]["label"] == item["label"]
        if not same_prev:
            points.add(item["start_ms"] + offset_ms)
        if not same_next:
            points.add(item["end_ms"] + offset_ms)
    return sorted(points)


def edge_windows(rows: list[dict], samples_per_window: int, median_dt: float, drops: Counter):
    """Membagi baris menjadi jendela edge tanpa tumpang tindih, sesuai nomor seq."""
    groups: dict[int, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["seq"] // samples_per_window, []).append(row)
    for index in sorted(groups):
        group = groups[index]
        if len(group) < samples_per_window:
            drops["edge_sampel_kurang"] += 1
            continue
        if any(b["t_mono_s"] - a["t_mono_s"] > GAP_FACTOR * median_dt for a, b in zip(group, group[1:])):
            drops["edge_gap"] += 1
            continue
        # Baris stale tetap ikut agar stale_count terhitung; hanya magnitude ekstrem yang membatalkan.
        if any(not r["valid"] and r["accel_fresh"] and r["gyro_fresh"] for r in group):
            drops["edge_sampel_tidak_valid"] += 1
            continue
        samples = [SensorSample(r["t_mono_s"], (r["ax"], r["ay"], r["az"]), (r["gx"], r["gy"], r["gz"]),
                                bool(r["accel_fresh"]), bool(r["gyro_fresh"])) for r in group]
        try:
            yield group[0]["t_epoch_ms"], group[-1]["t_epoch_ms"], compute_window_features(samples)
        except InvalidWindow:
            drops["edge_tidak_finite"] += 1


def session_rows(report, dataset_id: str, config: WindowConfig, guard_s: float, drops: Counter) -> list[dict]:
    meta = report.meta
    offset = int(meta.get("clock_offset_ms") or 0)
    points = boundaries(report.labels, offset)
    guard_ms = guard_s * 1000
    buffer = AggregateBuffer(config)
    window_labels: dict[int, str | None] = {}
    rows = []
    for start_ms, end_ms, window in edge_windows(report.rows, int(meta["samples_per_window"]), report.median_dt, drops):
        label = label_at(report.labels, offset, start_ms)
        if label != label_at(report.labels, offset, end_ms):
            label = None
        if label is not None and any(start_ms - guard_ms < p < end_ms + guard_ms for p in points):
            label = None
        if not window_usable(window):
            drops["edge_terlalu_banyak_stale"] += 1
        if not buffer.add(end_ms, window):
            if window_usable(window):
                drops["edge_waktu_mundur"] += 1
            continue
        window_labels[end_ms] = label
        features = buffer.aggregate()
        if features is None:
            drops["agregat_data_kurang"] += 1
            continue
        used = {window_labels[t] for t, _ in buffer.items}
        if len(used) != 1:
            drops["agregat_label_campur_atau_transisi"] += 1
            continue
        final = used.pop()
        if final not in TRAINING_LABELS:
            drops["agregat_uncertain_atau_tanpa_label"] += 1
            continue
        rows.append({"dataset_id": dataset_id, "session_id": meta["session_id"],
                     "session_type": meta["session_type"], "cycle_id": meta.get("cycle_id") or "",
                     "machine_id": meta["machine_id"], "device_id": meta["device_id"],
                     "data_kind": meta["data_kind"], **buffer.quality(), **features, "label": final})
    return rows


def _write_csv(path: Path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _raw_labeled(report) -> list[dict]:
    meta = report.meta
    offset = int(meta.get("clock_offset_ms") or 0)
    out, last = [], None
    for r in report.rows:
        out.append({**{k: r[k] for k in ("seq", "t_epoch_ms", "ax", "ay", "az", "gx", "gy", "gz",
                                         "accel_fresh", "gyro_fresh", "valid", "session_id")},
                    "device_id": meta["device_id"], "machine_id": meta["machine_id"],
                    "dt_s": "" if last is None else round(r["t_mono_s"] - last, 6),
                    "label": label_at(report.labels, offset, r["t_epoch_ms"]) or "UNLABELED"})
        last = r["t_mono_s"]
    return out


def build(root: Path, dataset_id: str, out_root: Path, config: WindowConfig | None = None,
          guard_s: float = TRANSITION_GUARD_S, overwrite: bool = False) -> dict:
    root, config = Path(root), config or WindowConfig()
    if root.name not in DATA_KINDS:
        raise DatasetError(f"--root harus berakhir pada folder real atau synthetic, bukan {root.name}")
    kind = root.name
    sessions = list_sessions(root) if root.exists() else []
    if not sessions:
        raise DatasetError(f"Dataset kosong: tidak ada sesi di {root}")
    out = Path(out_root) / dataset_id
    if out.exists() and not overwrite:
        raise DatasetError(f"Dataset {out} sudah ada dan tidak ditimpa")
    out.mkdir(parents=True, exist_ok=True)

    reports = [validate_session(p, kind, True) for p in sessions]
    rows, raw_rows, quarantined, per_session, drops = [], [], [], [], Counter()
    manifest_sessions = []
    for report, path in zip(reports, sessions):
        summary = report.summary()
        session_drops = Counter()
        session_windows = 0
        if not report.rejected:
            new = session_rows(report, dataset_id, config, guard_s, session_drops)
            rows.extend(new)
            session_windows = len(new)
            raw_rows.extend(_raw_labeled(report))
            quarantined.extend(dict(q, session_id=report.session_id) for q in report.quarantined)
            manifest_sessions.append({
                "session_id": report.session_id, "cycle_id": report.meta.get("cycle_id"),
                "machine_id": report.meta["machine_id"], "session_type": report.meta["session_type"],
                "program": report.meta.get("program"),
                "sha256": {n: sha256_file(path / n) for n in ("raw.csv", "meta.json", "labels.csv")},
            })
        drops.update(session_drops)
        per_session.append({**summary, "windows": session_windows, "drops": dict(session_drops)})
    if not rows:
        raise DatasetError("Dataset kosong setelah validasi. Lihat alasan pada quality_report.json di " + str(out))

    _write_csv(out / "windows.csv", WINDOW_COLUMNS, rows)
    _write_csv(out / "raw_labeled.csv", RAW_LABELED_COLUMNS, raw_rows)
    if quarantined:
        keys = sorted({k for q in quarantined for k in q})
        _write_csv(out / "quarantine.csv", keys, quarantined)
    manifest = {
        "dataset_id": dataset_id, "data_kind": kind, "raw_schema_version": RAW_SCHEMA_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION, "feature_columns": list(ALL_FEATURE_COLUMNS),
        "window": {"aggregate_s": config.aggregate_s, "min_windows": config.min_windows,
                   "min_coverage_s": config.min_coverage_s, "transition_guard_s": guard_s},
        "sessions": manifest_sessions, "windows_sha256": sha256_file(out / "windows.csv"),
        "n_windows": len(rows),
    }
    write_json(out / "manifest.json", manifest)
    quality = {
        "dataset_id": dataset_id, "data_kind": kind,
        "sessions_accepted": sum(not r.rejected for r in reports), "sessions_rejected": sum(r.rejected for r in reports),
        "rows_total": sum(r.n_total for r in reports),
        "rows_usable": sum(s["rows_usable"] for s in per_session if s["status"] == "ACCEPTED"),
        "rows_invalid": sum(s["rows_invalid"] for s in per_session),
        "rows_quarantined": sum(s["rows_quarantined"] for s in per_session),
        "windows": len(rows), "windows_per_label": dict(Counter(r["label"] for r in rows)),
        "windows_per_session": {s["session_id"]: s["windows"] for s in per_session},
        "drop_reasons": dict(sorted(drops.items())), "sessions": per_session,
    }
    write_json(out / "quality_report.json", quality)
    (out / "quality_report.md").write_text(_quality_md(quality), encoding="utf-8")
    return quality


def _quality_md(q: dict) -> str:
    lines = []
    if q["data_kind"] == "synthetic":
        lines += ["> **DATA SINTETIS. Hasil ini hanya menguji perangkat lunak, bukan performa pada mesin cuci nyata.**", ""]
    lines += [f"# Laporan kualitas data: {q['dataset_id']}", "", "| Ukuran | Nilai |", "|---|---|"]
    for key in ("data_kind", "sessions_accepted", "sessions_rejected", "rows_total", "rows_usable",
                "rows_invalid", "rows_quarantined", "windows"):
        lines.append(f"| {key} | {q[key]} |")
    lines += ["", "## Jendela per label", "", "| Label | Jumlah |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(q["windows_per_label"].items())]
    lines += ["", "## Alasan pembuangan", "", "| Alasan | Jumlah |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in q["drop_reasons"].items()] or ["| tidak ada | 0 |"]
    lines += ["", "## Per sesi", "", "| Sesi | Status | Median dt (dtk) | Jendela | Temuan |", "|---|---|---|---|---|"]
    for s in q["sessions"]:
        issues = "; ".join(f"{i['code']} {i['action']}: {i['message']}" for i in s["issues"]) or "-"
        lines.append(f"| {s['session_id']} | {s['status']} | {s['median_dt_s']} | {s['windows']} | {issues} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bangun dataset fitur")
    parser.add_argument("--root", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--out-root", default="data/processed")
    parser.add_argument("--aggregate-s", type=float, default=WindowConfig.aggregate_s)
    parser.add_argument("--min-windows", type=int, default=WindowConfig.min_windows)
    parser.add_argument("--min-coverage-s", type=float, default=WindowConfig.min_coverage_s)
    parser.add_argument("--guard-s", type=float, default=TRANSITION_GUARD_S)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        q = build(Path(args.root), args.dataset_id, Path(args.out_root),
                  WindowConfig(args.aggregate_s, args.min_windows, args.min_coverage_s), args.guard_s, args.overwrite)
    except DatasetError as exc:
        print(f"[DATASET] Ditolak: {exc}", file=sys.stderr)
        return 2
    print(f"[DATASET] {args.dataset_id} ({q['data_kind']}): {q['windows']} jendela, {q['windows_per_label']}, "
          f"sesi ditolak {q['sessions_rejected']}")
    if q["data_kind"] == "synthetic":
        print("[DATASET] DATA SINTETIS: hanya untuk menguji perangkat lunak.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
