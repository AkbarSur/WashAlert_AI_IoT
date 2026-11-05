"""Validasi sesi dan dataset (FR validator, DML kualitas data).

python -m ml.validate_dataset --root data/real

Tindakan: REJECT (sesi ditolak), QUARANTINE (baris dipisahkan), MARK_INVALID (sampel tidak
dipakai untuk fitur), WARN (dicatat). Tidak ada imputasi: data yang hilang tidak diisi.
Aturan lengkap ada di docs/data_quality_rules.md.
"""

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean, median

from ml.dataset_io import (ALL_LABELS, DATA_KINDS, LABEL_COLUMNS, META_REQUIRED, METHODS, RAW_COLUMNS,
                           SESSION_TYPES, UNITS, read_json, valid_code, valid_session_id)

REJECT, QUARANTINE, MARK_INVALID, WARN = "REJECT", "QUARANTINE", "MARK_INVALID", "WARN"
MAX_QUARANTINE_RATIO = 0.01   # diusulkan
MAX_SENSOR_MAG = 200.0        # m/s², di atas rentang akselerometer HP umum; diusulkan
MIN_ROWS = 10
GAP_FACTOR = 5
FLOATS = ("t_mono_s", "ax", "ay", "az", "gx", "gy", "gz")


@dataclass
class Issue:
    code: str
    action: str
    message: str
    count: int = 1


@dataclass
class SessionReport:
    session_id: str
    meta: dict | None = None
    rows: list = field(default_factory=list)
    quarantined: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    n_total: int = 0
    median_dt: float | None = None

    def add(self, code, action, message, count=1):
        self.issues.append(Issue(code, action, message, count))

    @property
    def rejected(self) -> bool:
        return any(i.action == REJECT for i in self.issues)

    @property
    def n_invalid(self) -> int:
        return sum(1 for r in self.rows if not r["valid"])

    def summary(self) -> dict:
        return {
            "session_id": self.session_id, "status": "REJECTED" if self.rejected else "ACCEPTED",
            "rows_total": self.n_total, "rows_usable": len(self.rows) - self.n_invalid,
            "rows_invalid": self.n_invalid, "rows_quarantined": len(self.quarantined),
            "median_dt_s": self.median_dt,
            "issues": [vars(i) for i in self.issues],
        }


def _parse_row(raw: dict) -> dict:
    """ValueError jika ada nilai hilang, bukan angka, atau tidak finite."""
    row = {"session_id": raw["session_id"], "seq": int(raw["seq"]), "t_epoch_ms": int(raw["t_epoch_ms"]),
           "accel_fresh": int(raw["accel_fresh"]), "gyro_fresh": int(raw["gyro_fresh"]), "valid": int(raw["valid"])}
    for key in FLOATS:
        value = float(raw[key])
        if not math.isfinite(value):
            raise ValueError(f"{key} tidak finite")
        row[key] = value
    if row["accel_fresh"] not in (0, 1) or row["gyro_fresh"] not in (0, 1) or row["valid"] not in (0, 1):
        raise ValueError("Flag harus 0 atau 1")
    return row


def _check_meta(report: SessionReport, meta: dict, session_dir: Path, expected_kind: str | None):
    for key in META_REQUIRED:
        if meta.get(key) in (None, ""):
            report.add("V04", REJECT, f"Metadata {key} kosong")
    if meta.get("session_id") != session_dir.name or not valid_session_id(meta.get("session_id")):
        report.add("V05", REJECT, "session_id tidak valid atau berbeda dengan nama folder")
    if meta.get("data_kind") not in DATA_KINDS:
        report.add("V06", REJECT, "data_kind harus real atau synthetic")
    if expected_kind and meta.get("data_kind") != expected_kind:
        report.add("V06", REJECT, f"data_kind {meta.get('data_kind')} berada di folder {expected_kind}")
    if meta.get("data_kind") == "real" and meta.get("source") != "android":
        report.add("V06", REJECT, "Data real harus bersumber dari android")
    if meta.get("session_type") not in SESSION_TYPES:
        report.add("V04", REJECT, "session_type tidak dikenal")
    if meta.get("session_type") == "cycle" and not valid_code(meta.get("cycle_id")):
        report.add("V04", REJECT, "Sesi cycle wajib punya cycle_id")
    if meta.get("units") != UNITS:
        report.add("V14", REJECT, f"Satuan harus {UNITS}, tercatat {meta.get('units')}")
    for key in ("operator", "machine_id", "device_id"):
        if meta.get(key) and not valid_code(meta[key]):
            report.add("V04", REJECT, f"{key} harus kode tanpa spasi")
    if meta.get("status") != "complete":
        report.add("V18", WARN, f"Rekaman berstatus {meta.get('status')}")
    if meta.get("sensor_fault_seen"):
        report.add("V11", WARN, "Sensor sempat tidak memberi nilai baru saat merekam")


def _check_rows(report: SessionReport, session_dir: Path):
    path = session_dir / "raw.csv"
    if not path.exists():
        report.add("V01", REJECT, "raw.csv tidak ada")
        return
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != RAW_COLUMNS:
            report.add("V01", REJECT, f"Kolom raw.csv tidak sesuai skema: {reader.fieldnames}")
            return
        seen = set()
        for number, raw in enumerate(reader, start=2):
            report.n_total += 1
            try:
                row = _parse_row(raw)
            except (TypeError, ValueError, KeyError) as exc:
                report.quarantined.append({"line": number, "reason": f"V02 {exc}", **raw})
                continue
            if row["session_id"] != report.session_id:
                report.add("V05", REJECT, f"Baris {number} milik sesi lain: {row['session_id']}")
                return
            if row["seq"] in seen:
                report.quarantined.append({"line": number, "reason": "V03 seq duplikat", **raw})
                continue
            seen.add(row["seq"])
            report.rows.append(row)

    if report.n_total == 0:
        report.add("V16", REJECT, "raw.csv kosong")
        return
    if report.quarantined:
        report.add("V02", QUARANTINE, "Baris rusak atau duplikat dipisahkan", len(report.quarantined))
        if len(report.quarantined) / report.n_total > MAX_QUARANTINE_RATIO and len(report.quarantined) > 1:
            report.add("V02", REJECT, f"Baris rusak lebih dari {MAX_QUARANTINE_RATIO:.0%}")
    if len(report.rows) < MIN_ROWS:
        report.add("V16", REJECT, f"Terlalu sedikit baris: {len(report.rows)}")
        return

    out_of_order = sum(1 for a, b in zip(report.rows, report.rows[1:])
                       if b["seq"] <= a["seq"] or b["t_mono_s"] < a["t_mono_s"])
    if out_of_order:
        report.add("V03", REJECT, "seq atau t_mono_s mundur. File tidak diurutkan ulang otomatis", out_of_order)
        return
    backwards = sum(1 for a, b in zip(report.rows, report.rows[1:]) if b["t_epoch_ms"] < a["t_epoch_ms"])
    if backwards:
        report.add("V19", WARN, "Jam epoch HP mundur. t_mono_s tetap menjadi acuan urutan", backwards)
    if any(r["t_epoch_ms"] <= 0 for r in report.rows):
        report.add("V03", REJECT, "t_epoch_ms tidak valid")
        return

    gaps = [b["t_mono_s"] - a["t_mono_s"] for a, b in zip(report.rows, report.rows[1:])]
    report.median_dt = round(median(gaps), 4)
    big = sum(1 for g in gaps if report.median_dt > 0 and g > GAP_FACTOR * report.median_dt)
    if big:
        report.add("V09", WARN, f"Gap lebih dari {GAP_FACTOR}× median. Jendela terkait dibuang", big)
    if report.median_dt == 0:
        report.add("V03", REJECT, "Semua timestamp sama")
        return

    # Sampel yang tercatat tidak valid tetap dipertahankan flag-nya, tidak diisi nilai lain.
    extreme = 0
    for row in report.rows:
        magnitude = math.sqrt(row["ax"] ** 2 + row["ay"] ** 2 + row["az"] ** 2)
        row["magnitude"] = magnitude
        row["omega"] = math.sqrt(row["gx"] ** 2 + row["gy"] ** 2 + row["gz"] ** 2)
        if magnitude > MAX_SENSOR_MAG:
            row["valid"] = 0
            extreme += 1
    if extreme:
        report.add("V20", MARK_INVALID, "Magnitude accel di luar rentang sensor", extreme)
    stale = sum(1 for r in report.rows if not (r["accel_fresh"] and r["gyro_fresh"]))
    if stale:
        report.add("V10", MARK_INVALID, "Sampel memakai nilai sensor lama", stale)
    for axis in ("ax", "ay", "az", "gx", "gy", "gz"):
        if len({r[axis] for r in report.rows}) == 1:
            report.add("V11", WARN, f"Sumbu {axis} bernilai sama sepanjang sesi. Sensor mungkin beku")


def _check_labels(report: SessionReport, session_dir: Path, require_labels: bool):
    path = session_dir / "labels.csv"
    if not path.exists():
        if require_labels:
            report.add("V07", REJECT, "labels.csv tidak ada")
        return
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != LABEL_COLUMNS:
            report.add("V07", REJECT, "Kolom labels.csv tidak sesuai skema")
            return
        for raw in reader:
            try:
                item = dict(raw, start_ms=int(raw["start_ms"]), end_ms=int(raw["end_ms"]))
            except (TypeError, ValueError):
                report.add("V07", REJECT, f"Waktu label tidak valid: {raw}")
                return
            if item["label"] not in ALL_LABELS:
                report.add("V07", REJECT, f"Label tidak dikenal: {item['label']}")
            if item["start_ms"] >= item["end_ms"]:
                report.add("V07", REJECT, f"Interval label terbalik: {raw}")
            if item["session_id"] != report.session_id:
                report.add("V05", REJECT, "Label milik sesi lain")
            if item["method"] not in METHODS or not valid_code(item["observer"]):
                report.add("V07", REJECT, "method atau observer label tidak valid")
            report.labels.append(item)
    if not report.labels:
        if require_labels:
            report.add("V07", REJECT, "labels.csv kosong")
        return
    ordered = sorted(report.labels, key=lambda r: r["start_ms"])
    if any(b["start_ms"] < a["end_ms"] for a, b in zip(ordered, ordered[1:])):
        report.add("V07", REJECT, "Interval label tumpang tindih")
    report.labels = ordered


def _check_cross(report: SessionReport):
    if report.rejected or not report.rows or not report.labels or not report.meta:
        return
    offset = report.meta.get("clock_offset_ms") or 0
    first, last = report.rows[0]["t_epoch_ms"], report.rows[-1]["t_epoch_ms"]
    outside = sum(1 for l in report.labels if l["end_ms"] + offset < first or l["start_ms"] + offset > last)
    if outside:
        report.add("V08", WARN, "Interval label di luar rentang rekaman. Bagian itu tidak terpakai", outside)
    present = {l["label"] for l in report.labels}
    if report.meta.get("session_type") == "cycle" and "SPIN" not in present:
        report.add("V13", WARN, "Siklus tanpa SPIN. Pastikan programnya memang tanpa spin")

    # Saat IDLE, magnitude rata-rata memberi petunjuk satuan dan offset.
    idle = [r for r in report.rows if r["valid"] and any(
        l["label"] == "IDLE" and l["start_ms"] + offset <= r["t_epoch_ms"] < l["end_ms"] + offset
        for l in report.labels)]
    sample = idle if len(idle) >= MIN_ROWS else report.rows
    usable = [r for r in sample if r["valid"]] or sample
    mean_mag = fmean(r["magnitude"] for r in usable)
    if 0.5 < mean_mag < 1.5:
        report.add("V14", REJECT, f"Magnitude {mean_mag:.2f}: accel tampak dalam g, bukan m/s^2. Tidak dikonversi otomatis")
    elif not 8.5 < mean_mag < 11.0 and len(idle) >= MIN_ROWS:
        report.add("V12", WARN, f"Magnitude rata-rata saat IDLE {mean_mag:.2f} m/s^2, jauh dari 9,81")
    elif not 5 < mean_mag < 20:
        report.add("V14", REJECT, f"Magnitude rata-rata {mean_mag:.2f} tidak wajar untuk m/s^2")
    if len(idle) >= MIN_ROWS:
        mean_omega = fmean(r["omega"] for r in idle)
        if mean_omega > 0.3:
            report.add("V15", WARN, f"Gyro saat IDLE {mean_omega:.2f}: periksa satuan rad/s atau label")


def validate_session(session_dir: Path, expected_kind: str | None = None, require_labels: bool = True) -> SessionReport:
    session_dir = Path(session_dir)
    report = SessionReport(session_dir.name)
    meta_path = session_dir / "meta.json"
    if not meta_path.exists():
        report.add("V04", REJECT, "meta.json tidak ada")
    else:
        try:
            report.meta = read_json(meta_path)
            _check_meta(report, report.meta, session_dir, expected_kind)
        except (ValueError, OSError) as exc:
            report.add("V04", REJECT, f"meta.json rusak: {exc}")
    _check_rows(report, session_dir)
    _check_labels(report, session_dir, require_labels)
    _check_cross(report)
    return report


def list_sessions(root: Path) -> list[Path]:
    return sorted(p for p in Path(root).iterdir() if p.is_dir())


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validasi folder sesi")
    parser.add_argument("--root", required=True)
    parser.add_argument("--no-labels-ok", action="store_true", help="Tidak mewajibkan labels.csv")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    root = Path(args.root)
    kind = root.name if root.name in DATA_KINDS else None
    sessions = list_sessions(root) if root.exists() else []
    if not sessions:
        print(f"[VALIDASI] DITOLAK: tidak ada sesi di {root}")
        return 2
    reports = [validate_session(p, kind, not args.no_labels_ok) for p in sessions]
    for r in reports:
        s = r.summary()
        print(f"{s['status']:9} {s['session_id']}: pakai {s['rows_usable']}, tidak valid {s['rows_invalid']}, "
              f"karantina {s['rows_quarantined']}")
        for i in r.issues:
            print(f"    {i.code} {i.action} ({i.count}): {i.message}")
    if args.json:
        args.json.write_text(json.dumps([r.summary() for r in reports], indent=2, ensure_ascii=False), encoding="utf-8")
    return 1 if any(r.rejected for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
