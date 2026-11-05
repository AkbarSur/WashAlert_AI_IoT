"""Skema dan baca-tulis file dataset. Pustaka standar saja, sehingga berjalan di Termux."""

import csv
import hashlib
import json
import re
from pathlib import Path

RAW_SCHEMA_VERSION = 2
RAW_COLUMNS = ("session_id", "seq", "t_mono_s", "t_epoch_ms", "dt_s", "ax", "ay", "az",
               "gx", "gy", "gz", "accel_fresh", "gyro_fresh", "valid")
LABEL_COLUMNS = ("session_id", "start_ms", "end_ms", "label", "phase_note", "observer", "method")
TRAINING_LABELS = ("IDLE", "WASHING", "SPIN")
ALL_LABELS = TRAINING_LABELS + ("UNCERTAIN",)
SESSION_TYPES = ("cycle", "idle", "disturbance", "segment", "measurement")
DATA_KINDS = ("real", "synthetic")
METHODS = ("direct", "video")
UNITS = {"accel": "m/s^2", "gyro": "rad/s"}
META_REQUIRED = ("schema_version", "session_id", "session_type", "data_kind", "device_id",
                 "phone_model", "machine_id", "machine_type", "program", "placement",
                 "orientation", "operator", "samples_per_window", "interval_s", "units", "source")

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")


def valid_session_id(value) -> bool:
    return isinstance(value, str) and bool(_ID.match(value))


def valid_code(value) -> bool:
    """Kode pseudonim: tanpa spasi, sehingga nama lengkap tidak lolos."""
    return isinstance(value, str) and bool(_CODE.match(value))


def normalize_label(value: str) -> str:
    label = str(value).strip().upper()
    if label == "DONE":
        raise ValueError("DONE bukan label sensor. DONE diputuskan FSM. Mesin diam berlabel IDLE.")
    if label not in ALL_LABELS:
        raise ValueError(f"Label tidak dikenal: {value!r}. Pilihan: {', '.join(ALL_LABELS)}")
    return label


def write_json(path: Path, data: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RawWriter:
    """Menulis raw.csv baris per baris dan flush, agar rekaman putus tetap terpakai."""

    def __init__(self, path: Path):
        self.handle = open(path, "x", newline="", encoding="utf-8")  # "x": tidak pernah menimpa
        self.writer = csv.writer(self.handle, lineterminator="\n")
        self.writer.writerow(RAW_COLUMNS)
        self.handle.flush()
        self.seq = 0
        self.last_mono = None

    def write(self, session_id: str, t_mono: float, t_epoch_ms: int, accel, gyro,
              accel_fresh: bool, gyro_fresh: bool, valid: bool):
        dt = "" if self.last_mono is None else f"{t_mono - self.last_mono:.6f}"
        self.writer.writerow([session_id, self.seq, f"{t_mono:.6f}", t_epoch_ms, dt,
                              *(f"{v:.6f}" for v in accel), *(f"{v:.6f}" for v in gyro),
                              int(accel_fresh), int(gyro_fresh), int(valid)])
        self.handle.flush()
        self.seq += 1
        self.last_mono = t_mono

    def close(self):
        self.handle.close()


def write_labels(path: Path, rows: list[dict]):
    with open(path, "x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
