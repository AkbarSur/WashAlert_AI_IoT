"""Generator data SINTETIS untuk menguji perangkat lunak (FR pemisahan data sintetis).

python -m ml.generate_synthetic --cycles 8 --seed 42

Profil amplitudo di sini adalah angka buatan, bukan hasil pengukuran mesin cuci.
Hasilnya tidak boleh dipakai untuk mengklaim akurasi pada mesin nyata.
"""

import argparse
import math
import random
import sys
from pathlib import Path

from ml.dataset_io import RAW_SCHEMA_VERSION, RawWriter, UNITS, write_json, write_labels

# (amplitudo vertikal, amplitudo horizontal, kecepatan sudut). Buatan.
PROFILE = {"IDLE": (0.0, 0.0, 0.0), "WASHING": (0.35, 0.45, 0.05), "SPIN": (2.0, 2.6, 0.45)}
# (label, menit, catatan). Buatan, urutannya mengikuti pola umum: cuci, jeda, bilas, spin.
CYCLE = (("IDLE", 2, ""), ("WASHING", 12, ""), ("IDLE", 2, "soak"), ("WASHING", 5, "rinse"), ("SPIN", 2, ""),
         ("IDLE", 1, "fill"), ("WASHING", 4, "rinse"), ("SPIN", 4, ""), ("IDLE", 3, ""))
T0_MS = 1_790_000_000_000
PREFIX = "SYNTHETIC_"


def _write_session(root: Path, session: str, session_type: str, cycle_id, machine: str, plan, seed: int,
                   rate_hz: float, gyro_gap: float, t0_ms: int, difficulty: str = "easy"):
    rng = random.Random(seed)
    folder = root / session
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "SYNTHETIC_DATA_DO_NOT_REPORT_AS_REAL").write_text("Data buatan generator.\n", encoding="utf-8")
    # "hard" membuat kelas tumpang tindih agar kesalahan model dan confusion matrix dapat diuji.
    hard = difficulty == "hard"
    scale = rng.uniform(0.25, 1.8) if hard else rng.uniform(0.8, 1.2)
    noise = 0.12 if hard else 0.03
    offset = rng.uniform(-0.15, 0.15)
    tilt = rng.uniform(0.0, 0.25)
    gravity = ((9.81 + offset) * math.sin(tilt), 0.0, (9.81 + offset) * math.cos(tilt))
    writer = RawWriter(folder / "raw.csv")
    t, labels, n, last_gyro = 0.0, [], 0, (0.0, 0.0, 0.0)
    for label, minutes, note in plan:
        start = t
        v, h, w = PROFILE[label]
        if hard:
            phase = rng.uniform(0.5, 1.5)
            v, h, w = v * phase, h * phase, w * phase
            if label == "IDLE" and rng.random() < 0.3:   # getaran latar, misalnya mesin lain
                v, h, w = 0.12 / scale, 0.12 / scale, 0.02 / scale
        while t - start < minutes * 60:
            s = math.sin(2 * math.pi * rng.uniform(5, 20) * t + rng.random() * 6.28)
            c = math.cos(2 * math.pi * rng.uniform(5, 20) * t + rng.random() * 6.28)
            burst = rng.uniform(0.2, 1.3) if hard and label != "IDLE" else 1.0
            accel = (gravity[0] + burst * scale * h * s + rng.gauss(0, noise), burst * scale * h * c + rng.gauss(0, noise),
                     gravity[2] + burst * scale * v * c + rng.gauss(0, noise))
            fresh_gyro = rng.random() >= gyro_gap
            if fresh_gyro:
                last_gyro = (scale * w * abs(s) + rng.gauss(0, 0.01), rng.gauss(0, 0.01), rng.gauss(0, 0.01))
            writer.write(session, 1000 + t, t0_ms + int(t * 1000), accel, last_gyro, True, fresh_gyro, fresh_gyro)
            n += 1
            t += max(0.05, rng.gauss(1 / rate_hz, 0.05 / rate_hz))
        labels.append({"session_id": session, "start_ms": t0_ms + int(start * 1000), "end_ms": t0_ms + int(t * 1000),
                       "label": label, "phase_note": note, "observer": "GEN", "method": "direct"})
    writer.close()
    write_labels(folder / "labels.csv", labels)
    write_json(folder / "meta.json", {
        "schema_version": RAW_SCHEMA_VERSION, "session_id": session, "cycle_id": cycle_id, "session_type": session_type,
        "data_kind": "synthetic", "source": "generate_synthetic", "device_id": "edge1", "phone_model": "SINTETIS",
        "machine_id": machine, "machine_type": "SINTETIS", "program": "SINTETIS", "placement": "SINTETIS",
        "orientation": "SINTETIS", "operator": "GEN", "samples_per_window": 5, "interval_s": 0.1, "units": UNITS,
        "clock_offset_ms": 0, "notes": "Data buatan generator, bukan pengukuran", "status": "complete",
        "n_rows": n, "n_invalid": 0, "n_stale": 0, "sensor_fault_seen": False, "seed": seed, "difficulty": difficulty,
    })


def generate(root: Path, cycles: int = 8, idle_sessions: int = 2, machines: int = 1, seed: int = 42,
             rate_hz: float = 1.6, gyro_gap: float = 0.03, time_scale: float = 1.0, difficulty: str = "easy") -> list[str]:
    root = Path(root)
    if root.name != "synthetic":
        raise ValueError("Data sintetis hanya boleh ditulis ke folder bernama synthetic")
    root.mkdir(parents=True, exist_ok=True)
    plan = [(l, m * time_scale, n) for l, m, n in CYCLE]
    names = []
    for i in range(cycles):
        machine = f"SYNM{i % machines + 1}"
        name = f"{PREFIX}{machine}_C{i + 1:02d}"
        _write_session(root, name, "cycle", f"{machine}_C{i + 1:02d}", machine, plan, seed + i, rate_hz, gyro_gap,
                       T0_MS + i * 7_200_000, difficulty)
        names.append(name)
    for i in range(idle_sessions):
        name = f"{PREFIX}IDLE_{i + 1:02d}"
        _write_session(root, name, "idle", None, f"SYNM{i % machines + 1}", [("IDLE", 10 * time_scale, "")],
                       seed + 1000 + i, rate_hz, gyro_gap, T0_MS + (cycles + i) * 7_200_000, difficulty)
        names.append(name)
    return names


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generator data SINTETIS")
    parser.add_argument("--root", default="data/synthetic")
    parser.add_argument("--cycles", type=int, default=8)
    parser.add_argument("--idle-sessions", type=int, default=2)
    parser.add_argument("--machines", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rate-hz", type=float, default=1.6)
    parser.add_argument("--time-scale", type=float, default=1.0)
    parser.add_argument("--difficulty", choices=["easy", "hard"], default="easy")
    args = parser.parse_args(argv)
    try:
        names = generate(Path(args.root), args.cycles, args.idle_sessions, args.machines, args.seed,
                         args.rate_hz, time_scale=args.time_scale, difficulty=args.difficulty)
    except (ValueError, FileExistsError) as exc:
        print(f"[SINTETIS] Ditolak: {exc}", file=sys.stderr)
        return 2
    print(f"[SINTETIS] {len(names)} sesi di {args.root}. DATA BUATAN, bukan pengukuran.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
