"""CLI Android dijalankan sebagai proses nyata dengan program termux-sensor tiruan.

Menguji alur kode --source android dari ujung ke ujung. Ini tetap BUKAN HP sungguhan.
"""
import csv
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAKE = """#!/usr/bin/env python3
import json, random, sys
args = sys.argv[1:]
if "-l" in args:
    print(json.dumps({"sensors": ["LSM6DSOTR Accelerometer", "LSM6DSOTR Gyroscope"]}))
elif "-c" in args:
    pass
else:
    n = int(args[args.index("-n") + 1])
    names = args[args.index("-s") + 1].split(",")
    for _ in range(n):
        out = {}
        for name in names:
            value = [random.gauss(0, .02), random.gauss(0, .02), 9.81] if "Accel" in name else [0.0, 0.0, 0.0]
            out[name] = {"values": value}
        print(json.dumps(out))
"""


class FakeTermuxCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        tool = self.base / "bin" / "termux-sensor"
        tool.parent.mkdir()
        tool.write_text(FAKE)
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
        self.env = dict(os.environ, PATH=f"{tool.parent}{os.pathsep}{os.environ['PATH']}", PYTHONDONTWRITEBYTECODE="1")

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", *args], cwd=ROOT, env=self.env, capture_output=True, text=True, timeout=120)

    def test_record_then_validate_as_real_source_path(self):
        root = self.base / "real"
        result = self.run_cli("ml.record_session", "--session", "sesi_cli", "--session-type", "idle", "--machine-id", "M1",
                              "--machine-type", "uji", "--phone-model", "uji", "--placement", "meja", "--orientation", "layar_atas",
                              "--operator", "A1", "--root", str(root), "--max-samples", "12", "--interval", "0.01",
                              "--label", "IDLE", "--observer", "A1")
        self.assertEqual(result.returncode, 0, result.stderr)
        meta = json.loads((root / "sesi_cli" / "meta.json").read_text())
        self.assertEqual((meta["data_kind"], meta["source"], meta["accel_sensor"]), ("real", "android", "LSM6DSOTR Accelerometer"))
        self.assertEqual(meta["status"], "complete")
        with open(root / "sesi_cli" / "raw.csv", newline="") as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 12)
        result = self.run_cli("ml.validate_dataset", "--root", str(root))
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_measure_tool_reports_rate_and_stream_probe(self):
        result = self.run_cli("ml.measure_sampling", "--phone", "uji", "--duration", "2", "--interval", "0.01", "--out-dir", str(self.base / "r"))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.base / "r" / "sampling_uji.json").read_text())
        self.assertGreater(report["rate_median_hz"], 0)
        self.assertEqual(report["stream_probe"]["objects"], 100)
        self.assertIn("wajar", report["unit_check"])

    def test_missing_termux_gives_clear_error(self):
        env = dict(self.env, PATH=str(self.base))
        result = subprocess.run([sys.executable, "-m", "ml.measure_sampling", "--phone", "u"], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("termux-sensor", result.stderr)


if __name__ == "__main__":
    unittest.main()
