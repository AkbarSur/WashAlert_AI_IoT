"""Pembantu test: sesi kecil buatan. Bukan data pengukuran."""
import csv
from pathlib import Path

from ml.dataset_io import RAW_COLUMNS, RawWriter, UNITS, write_json, write_labels

T0 = 1_790_000_000_000


def meta(session, kind="synthetic", session_type="cycle", cycle_id="C1", machine="M1", **kw):
    data = {"schema_version": 2, "session_id": session, "cycle_id": cycle_id if session_type == "cycle" else None,
            "session_type": session_type, "data_kind": kind, "source": "android" if kind == "real" else "generate_synthetic",
            "device_id": "edge1", "phone_model": "uji", "machine_id": machine, "machine_type": "uji", "program": "uji",
            "placement": "uji", "orientation": "uji", "operator": "A1", "samples_per_window": 5, "interval_s": 0.1,
            "units": UNITS, "clock_offset_ms": 0, "notes": "", "status": "complete"}
    data.update(kw)
    return data


def make_session(root, session="sesi_uji", phases=(("IDLE", 60), ("WASHING", 120), ("SPIN", 60), ("IDLE", 60)),
                 kind="synthetic", dt=0.5, gravity=9.81, labels=True, **meta_kw):
    """phases: (label, detik). Getaran tiap fase berbeda agar fitur dapat diperiksa."""
    folder = Path(root) / session
    folder.mkdir(parents=True)
    amp = {"IDLE": 0.0, "WASHING": 0.5, "SPIN": 3.0, "UNCERTAIN": 1.0}
    writer = RawWriter(folder / "raw.csv")
    t, intervals, sign = 0.0, [], 1
    for label, seconds in phases:
        start = t
        while t - start < seconds:
            sign = -sign
            a = amp[label] * sign
            writer.write(session, 100 + t, T0 + int(t * 1000), (a, 0.01 * sign, gravity), (amp[label] / 10, 0.0, 0.0), True, True, True)
            t += dt
        intervals.append({"session_id": session, "start_ms": T0 + int(start * 1000), "end_ms": T0 + int(t * 1000),
                          "label": label, "phase_note": "", "observer": "A1", "method": "direct"})
    writer.close()
    if labels:
        write_labels(folder / "labels.csv", intervals)
    write_json(folder / "meta.json", meta(session, kind, **meta_kw))
    return folder


def read_raw(folder):
    with open(Path(folder) / "raw.csv", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_raw(folder, rows):
    with open(Path(folder) / "raw.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
