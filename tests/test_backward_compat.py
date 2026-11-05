"""Regresi: alat lama tetap berjalan, dan modul inti tidak bergantung pada MQTT atau ML."""
import inspect
import subprocess
import sys
import unittest

from nodes.detector_service import rules
from shared import edge_runner
from shared.processing import SensorSample, extract_features


class BackwardCompatTests(unittest.TestCase):
    def test_offline_demo_still_runs(self):
        out = subprocess.run([sys.executable, "-m", "scripts.offline_demo"], capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.count("NOTIFIKASI KE HP B"), 1)
        self.assertIn("Pemilik konfirmasi", out)

    def test_sensor_sample_positional_form_unchanged(self):
        s = SensorSample(1.0, (0, 0, 9.81), (0, 0, 0))
        self.assertTrue(s.accel_fresh and s.gyro_fresh)
        self.assertEqual(extract_features([s, SensorSample(2.0, (0, 0, 9.81), (0, 0, 0))]).motion_rms, 0)

    def test_rules_has_no_mqtt_dependency(self):
        self.assertNotIn("paho", inspect.getsource(rules))
        code = "import sys, nodes.detector_service.rules; assert 'paho' not in {m.split('.')[0] for m in sys.modules}"
        subprocess.run([sys.executable, "-c", code], check=True)

    def test_edge_still_has_no_ml_dependency(self):
        code = "import sys, shared.edge_runner; assert not {'numpy','sklearn','joblib'} & {m.split('.')[0] for m in sys.modules}"
        subprocess.run([sys.executable, "-c", code], check=True)

    def test_cli_arguments_of_edge_preserved(self):
        source = inspect.getsource(edge_runner._parse_args)
        for flag in ("--source", "--scenario", "--interval", "--samples", "--debug-sensors"):
            self.assertIn(flag, source)


if __name__ == "__main__":
    unittest.main()
