"""Uji ketahanan NFR-006: detector, HP A, dan HP B simulator berjalan lama dengan broker lokal. SIMULATION.

    python -m scripts.soak_test --minutes 60 --out reports/soak

Butuh amqtt. Hasil membuktikan proses tidak crash dan memori tidak terus naik dengan simulator, bukan ketahanan HP nyata.
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def rss_mb(pid):
    text = Path(f"/proc/{pid}/status").read_text()
    return int(re.search(r"VmRSS:\s+(\d+)", text).group(1)) / 1024


def cpu_s(pid):
    stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return (int(stat[11]) + int(stat[12])) / os.sysconf("SC_CLK_TCK")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=60)
    parser.add_argument("--out", type=Path, default=ROOT / "reports/soak")
    parser.add_argument("--model", default="")
    args = parser.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="washalert_soak_"))
    port = free_port()
    (tmp / "broker.yaml").write_text(f"""listeners:
  default:
    type: tcp
    bind: 127.0.0.1:{port}
plugins:
  amqtt.plugins.authentication.AnonymousAuthPlugin:
    allow_anonymous: true
""")
    env = {**os.environ, "PROJECT_ID": "soak", "MQTT_HOST": "127.0.0.1", "MQTT_PORT": str(port), "MQTT_TLS": "false", "ALLOW_INSECURE_LOCAL": "true",
           "CUCI_MODE": "demo", "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1", "DASHBOARD_PORT": str(free_port()), "MQTT_WS_URL": ""}
    if args.model:
        env.update(DETECTION_MODE="HYBRID", MODEL_PATH=args.model, ALLOW_SYNTHETIC_MODEL="true")
    procs = {"broker": subprocess.Popen(["amqtt", "-c", str(tmp / "broker.yaml")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)}
    time.sleep(3)
    logs = {}
    for name, cmd in (("detector", ["detector.py"]), ("hp_a", ["hp_mesin.py", "--source", "simulator", "--scenario", "washer"]), ("hp_b", ["hp_pemilik.py", "--source", "simulator", "--scenario", "still"])):
        logs[name] = tmp / f"{name}.log"
        procs[name] = subprocess.Popen([sys.executable, *cmd], cwd=ROOT, env=env, stdout=open(logs[name], "w"), stderr=subprocess.STDOUT)
    samples, started = [], time.time()
    crashed = None
    while time.time() - started < args.minutes * 60:
        time.sleep(30)
        dead = [n for n, p in procs.items() if p.poll() is not None]
        if dead:
            crashed = dead
            break
        samples.append({"t_s": round(time.time() - started), "rss_mb": {n: round(rss_mb(procs[n].pid), 1) for n in ("detector", "hp_a", "hp_b")}})
    elapsed = time.time() - started
    cpu = cpu_s(procs["detector"].pid) if procs["detector"].poll() is None else None
    for p in procs.values():
        if p.poll() is None:
            p.kill()
            p.wait()
    text = {n: f.read_text(errors="replace") for n, f in logs.items()}
    third = max(1, len(samples) // 3)
    avg = lambda rows: round(sum(r["rss_mb"]["detector"] for r in rows) / len(rows), 1) if rows else None
    report = {"evidence_class": "SIMULATION", "minutes_requested": args.minutes, "minutes_elapsed": round(elapsed / 60, 1), "crashed": crashed,
              "detection_mode": "HYBRID" if args.model else "RULE_ONLY",
              "detector_rss_mb_first_third": avg(samples[:third]), "detector_rss_mb_last_third": avg(samples[-third:]),
              "detector_cpu_percent_one_core": round(100 * cpu / elapsed, 2) if cpu is not None else None,
              "telemetry_handled": text["detector"].count("rms="),
              "alerts": text["detector"].count(">>> ALERT"),
              "tracebacks": {n: t.count("Traceback") for n, t in text.items()},
              "handler_errors": text["detector"].count("Galat")}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "soak_report.json").write_text(json.dumps({**report, "samples": samples}, indent=1))
    print(json.dumps(report, indent=1))
    raise SystemExit(1 if crashed or any(report["tracebacks"].values()) else 0)


if __name__ == "__main__":
    main()
