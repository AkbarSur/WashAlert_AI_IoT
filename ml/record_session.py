"""Merekam sampel mentah dari sumber sensor WashAlert (FR perekaman, identitas sesi).

Di HP A (Termux):
  python -m ml.record_session --session 20261105_M1_HPA_01 --session-type cycle \
      --cycle-id M1_C01 --machine-id M1 --machine-type top_load --program normal \
      --phone-model hpA --placement atas_tutup_tengah --orientation layar_atas --operator A1

Label tidak pernah dibuat dari prediksi. `--label` hanya untuk sesi satu kondisi yang diamati
langsung. Sesi satu siklus dilabeli terpisah dengan ml.label_session.
"""

import argparse
import math
import os
import signal
import sys
import time
from pathlib import Path

from ml.dataset_io import (RAW_SCHEMA_VERSION, RawWriter, SESSION_TYPES, UNITS, normalize_label,
                           valid_code, valid_session_id, write_json, write_labels)
from shared.sensors import select_source

SOURCE_KIND = {"android": "real", "simulator": "synthetic"}
DEFAULT_ROOT = {"real": "data/real", "synthetic": "data/synthetic"}


class SessionError(ValueError):
    pass


def check_args(session, session_type, cycle_id, machine_id, device_id, operator, label, observer):
    if not valid_session_id(session):
        raise SessionError("--session: 3-64 karakter huruf, angka, _ atau -")
    if session_type not in SESSION_TYPES:
        raise SessionError(f"--session-type harus salah satu dari {SESSION_TYPES}")
    if session_type == "cycle" and not valid_code(cycle_id):
        raise SessionError("Sesi cycle wajib punya --cycle-id")
    if session_type != "cycle" and cycle_id:
        raise SessionError("--cycle-id hanya untuk sesi cycle")
    for name, value in (("--machine-id", machine_id), ("--device-id", device_id), ("--operator", operator)):
        if not valid_code(value):
            raise SessionError(f"{name}: pakai kode pseudonim tanpa spasi, bukan nama lengkap")
    if label is not None:
        normalize_label(label)
        if session_type == "cycle":
            raise SessionError("Satu siklus punya beberapa fase. Pakai ml.label_session, bukan --label")
        if not valid_code(observer):
            raise SessionError("--label membutuhkan --observer")


def build_meta(args, data_kind: str, source) -> dict:
    return {
        "schema_version": RAW_SCHEMA_VERSION,
        "session_id": args.session,
        "cycle_id": args.cycle_id,
        "session_type": args.session_type,
        "data_kind": data_kind,
        "source": args.source,
        "device_id": args.device_id,
        "phone_model": args.phone_model,
        "machine_id": args.machine_id,
        "machine_type": args.machine_type,
        "program": args.program,
        "placement": args.placement,
        "orientation": args.orientation,
        "operator": args.operator,
        "samples_per_window": args.samples,
        "interval_s": args.interval,
        "units": UNITS,
        "accel_sensor": getattr(source, "accel_name", None),
        "gyro_sensor": getattr(source, "gyro_name", None),
        "clock_offset_ms": 0,
        "notes": args.notes,
        "status": "recording",
    }


def record(source, session_dir: Path, meta: dict, duration_s: float | None, max_samples: int | None,
           label: str | None = None, observer: str | None = None,
           sleep=time.sleep, clock=time.time, log=print) -> dict:
    """Loop perekaman. Pola read dan sleep sama dengan shared/edge_runner.py."""
    raw_path = session_dir / "raw.csv"
    if raw_path.exists() or (session_dir / "meta.json").exists():
        raise SessionError(f"Sesi sudah ada dan tidak akan ditimpa: {session_dir}")
    session_dir.mkdir(parents=True, exist_ok=True)
    writer = RawWriter(raw_path)
    write_json(session_dir / "meta.json", meta)

    samples = invalid = stale = 0
    fault_seen = False
    first_ms = last_ms = None
    started = clock()
    every = max(int(meta["samples_per_window"]), 1)
    status = "complete"
    try:
        while True:
            if max_samples is not None and samples >= max_samples:
                break
            if duration_s is not None and clock() - started >= duration_s:
                break
            sample = source.read()
            now_ms = int(clock() * 1000)
            values = (*sample.acceleration, *sample.gyroscope)
            fresh = sample.accel_fresh and sample.gyro_fresh
            valid = fresh and all(math.isfinite(v) for v in values)
            writer.write(meta["session_id"], sample.seconds, now_ms, sample.acceleration, sample.gyroscope,
                         sample.accel_fresh, sample.gyro_fresh, valid)
            samples += 1
            invalid += not valid
            stale += not fresh
            first_ms = first_ms if first_ms is not None else now_ms
            last_ms = now_ms
            fault = bool(getattr(source, "sensor_fault", False))
            if fault and not fault_seen:
                log("[REKAM] PERINGATAN: sensor tidak memberi nilai baru. Periksa HP.")
            fault_seen = fault_seen or fault
            if samples % 60 == 0:
                log(f"[REKAM] {samples} sampel, tidak valid {invalid}, {clock() - started:.0f} dtk")
            if samples % every != 0:
                sleep(meta["interval_s"])
    except KeyboardInterrupt:
        status = "interrupted"
        log("[REKAM] Dihentikan. Data yang sudah tertulis tetap aman.")
    finally:
        writer.close()
        meta.update(status=status, n_rows=samples, n_invalid=invalid, n_stale=stale,
                    sensor_fault_seen=fault_seen, started_ms=first_ms, ended_ms=last_ms)
        write_json(session_dir / "meta.json", meta)

    if label is not None and samples:
        write_labels(session_dir / "labels.csv", [{
            "session_id": meta["session_id"], "start_ms": first_ms, "end_ms": last_ms + 1,
            "label": normalize_label(label), "phase_note": "", "observer": observer, "method": "direct",
        }])
    return meta


def _load_env():
    """SENSOR_ACCEL dan SENSOR_GYRO dapat berada di .env, sama seperti edge."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Rekam sesi sensor WashAlert AI")
    parser.add_argument("--session", required=True)
    parser.add_argument("--session-type", required=True, choices=SESSION_TYPES)
    parser.add_argument("--cycle-id")
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--machine-type", required=True)
    parser.add_argument("--program", default="tidak_berlaku")
    parser.add_argument("--phone-model", required=True)
    parser.add_argument("--placement", required=True)
    parser.add_argument("--orientation", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--device-id", default="edge1")
    parser.add_argument("--notes", default="")
    parser.add_argument("--label", help="Label seluruh sesi hasil observasi: IDLE, WASHING, SPIN, UNCERTAIN")
    parser.add_argument("--observer")
    parser.add_argument("--duration", type=float, help="Detik. Tanpa nilai ini: sampai Ctrl+C")
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--source", choices=["android", "simulator"], default="android")
    parser.add_argument("--scenario", choices=["still", "washer", "ack"], default="washer")
    parser.add_argument("--samples", type=int, default=5, help="Sampel per jendela, sama dengan edge")
    parser.add_argument("--interval", type=float, default=None)
    parser.add_argument("--root", help="Folder induk sesi. Bawaan mengikuti sumber data")
    args = parser.parse_args(argv)
    _load_env()

    data_kind = SOURCE_KIND[args.source]
    root = Path(args.root or DEFAULT_ROOT[data_kind])
    if args.interval is None:
        args.interval = 0.1 if args.source == "android" else 0.35
    try:
        check_args(args.session, args.session_type, args.cycle_id, args.machine_id, args.device_id,
                   args.operator, args.label, args.observer)
        other = "real" if data_kind == "synthetic" else "synthetic"
        if root.name == other:
            raise SessionError(f"Sumber {args.source} menghasilkan data {data_kind}, tidak boleh ke {root}")
        session_dir = root / args.session
        if (session_dir / "raw.csv").exists():
            raise SessionError(f"Sesi sudah ada dan tidak akan ditimpa: {session_dir}")
        source = select_source(args.source, args.scenario)
    except (SessionError, ValueError, RuntimeError) as exc:
        print(f"[REKAM] Ditolak: {exc}", file=sys.stderr)
        return 2

    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    meta = build_meta(args, data_kind, source)
    if os.getenv("TERMUX_VERSION"):
        print("[REKAM] Saran: jalankan termux-wake-lock agar Android tidak menghentikan rekaman.")
    print(f"[REKAM] Sesi {args.session} ({data_kind}) ke {session_dir}. Ctrl+C untuk berhenti.", flush=True)
    meta = record(source, session_dir, meta, args.duration, args.max_samples, args.label, args.observer)
    print(f"[REKAM] {meta['status']}: {meta['n_rows']} sampel, tidak valid {meta['n_invalid']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
