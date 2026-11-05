"""Mengukur laju sensor nyata satu HP (FR alat ukur sampling, gerbang G1).

Di HP diam:  python -m ml.measure_sampling --phone hpA --duration 120
"""

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from statistics import fmean, median

from ml.dataset_io import write_json
from shared.sensors import select_source


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(int(fraction * len(ordered)), len(ordered) - 1)]


def summarize(samples: list) -> dict:
    if len(samples) < 2:
        raise ValueError("Minimal 2 sampel untuk mengukur laju")
    gaps = [b.seconds - a.seconds for a, b in zip(samples, samples[1:])]
    mags = [math.sqrt(sum(v * v for v in s.acceleration)) for s in samples]
    omegas = [math.sqrt(sum(v * v for v in s.gyroscope)) for s in samples]
    n = len(samples)
    return {
        "n_samples": n,
        "interval_median_s": round(median(gaps), 4),
        "interval_p05_s": round(percentile(gaps, 0.05), 4),
        "interval_p95_s": round(percentile(gaps, 0.95), 4),
        "rate_median_hz": round(1 / median(gaps), 3) if median(gaps) > 0 else 0.0,
        "accel_empty_pct": round(100 * sum(not s.accel_fresh for s in samples) / n, 2),
        "gyro_empty_pct": round(100 * sum(not s.gyro_fresh for s in samples) / n, 2),
        "rest_offset_mps2": round(fmean(mags) - 9.81, 4),
        "rest_gyro_rad_s": round(fmean(omegas), 4),
        "unit_check": unit_check(fmean(mags), fmean(omegas)),
    }


def unit_check(mean_mag: float, mean_omega: float) -> str:
    """Hanya bermakna jika HP diam saat diukur."""
    if 0.5 < mean_mag < 1.5:
        return "accel tampak dalam g, bukan m/s^2"
    if not 8.5 < mean_mag < 11:
        return "magnitude accel saat diam tidak wajar"
    if mean_omega > 0.3:
        return "gyro saat diam tinggi: HP bergerak, atau satuan bukan rad/s"
    return "wajar untuk m/s^2 dan rad/s"


def probe_stream(sensors: str, delay_ms: int, count: int, run=subprocess.run, clock=time.monotonic) -> dict:
    """Coba satu panggilan panjang termux-sensor untuk menilai opsi streaming pada G1."""
    started = clock()
    output = run(["termux-sensor", "-s", sensors, "-d", str(delay_ms), "-n", str(count)],
                 capture_output=True, text=True, timeout=max(60, count), check=False).stdout
    elapsed = clock() - started
    decoder, index, objects = json.JSONDecoder(), 0, 0
    while True:
        index = output.find("{", index)
        if index == -1:
            break
        try:
            _, index = decoder.raw_decode(output, index)
            objects += 1
        except ValueError:
            index += 1
    return {"requested": count, "delay_ms": delay_ms, "objects": objects, "elapsed_s": round(elapsed, 3),
            "objects_per_s": round(objects / elapsed, 3) if elapsed > 0 else 0.0}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ukur laju sensor")
    parser.add_argument("--phone", required=True)
    parser.add_argument("--duration", type=float, default=120)
    parser.add_argument("--source", choices=["android", "simulator"], default="android")
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--no-stream-probe", action="store_true")
    parser.add_argument("--out-dir", default="reports")
    args = parser.parse_args(argv)
    try:
        source = select_source(args.source, "still")
    except (RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"[UKUR] Gagal membuka sensor: {exc}", file=sys.stderr)
        return 2
    samples, started = [], time.monotonic()
    while time.monotonic() - started < args.duration:
        samples.append(source.read())
        time.sleep(args.interval)
    result = {"phone": args.phone, "source": args.source,
              "note": "HP harus diam. Hasil berlaku untuk HP ini.", **summarize(samples)}
    if args.source == "android" and not args.no_stream_probe:
        result["stream_probe"] = probe_stream(f"{source.accel_name},{source.gyro_name}", 20, 100)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / f"sampling_{args.phone}.json", result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
