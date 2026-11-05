"""FR akuisisi sensor. Memakai mock termux-sensor; belum membuktikan perilaku HP nyata."""
import json
import unittest
from unittest import mock

from shared import sensors

ACC, GYR = "lsm6dso_acc", "BMI160 Gyroscope"


def fake_run(state):
    def run(cmd, **kwargs):
        result = mock.Mock()
        if "-l" in cmd:
            result.stdout = json.dumps({"sensors": state.get("names", [ACC, GYR, "x uncalibrated gyroscope"])})
        elif "-c" in cmd:
            result.stdout = ""
        else:
            out = {}
            if ACC in cmd[2] and state.get("accel", True):
                out[ACC] = {"values": state.get("accel_values", [0, 0, 9.81])}
            if GYR in cmd[2] and state.get("gyro", True):
                out[GYR] = {"values": [0.1, 0, 0]}
            result.stdout = json.dumps(out)
        return result
    return run


class AndroidSourceTests(unittest.TestCase):
    def open(self, state):
        patches = [mock.patch.object(sensors.shutil, "which", return_value="x"),
                   mock.patch.object(sensors.subprocess, "run", fake_run(state)),
                   mock.patch.object(sensors.time, "sleep")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with mock.patch("builtins.print"):
            return sensors.AndroidTermux()

    def test_detects_vendor_sensor_names_and_skips_uncalibrated(self):
        src = self.open({})
        self.assertEqual((src.accel_name, src.gyro_name), (ACC, GYR))

    def test_env_override_wins(self):
        with mock.patch.dict("os.environ", {"SENSOR_GYRO": "khusus"}):
            self.assertEqual(self.open({}).gyro_name, "khusus")

    def test_missing_sensor_lists_available_names(self):
        with self.assertRaisesRegex(RuntimeError, "Daftar"):
            self.open({"names": ["cahaya"]})

    def test_fresh_reading(self):
        s = self.open({}).read()
        self.assertTrue(s.accel_fresh and s.gyro_fresh)
        self.assertEqual(s.acceleration, (0.0, 0.0, 9.81))

    def test_missing_gyro_is_marked_not_zero_filled(self):
        state = {}
        src = self.open(state)
        src.read()
        state["gyro"] = False
        with mock.patch("builtins.print"):
            s = src.read()
        self.assertFalse(s.gyro_fresh)
        self.assertTrue(s.accel_fresh)
        self.assertEqual(s.gyroscope, (0.1, 0.0, 0.0))  # nilai lama, ditandai, bukan nol

    def test_gyro_never_read_raises_instead_of_inventing_values(self):
        src = self.open({"gyro": False})
        with self.assertRaisesRegex(RuntimeError, "20x"):
            src.read()

    def test_sensor_fault_after_repeated_empty_reads_and_recovery(self):
        state = {}
        src = self.open(state)
        src.read()
        state["accel"] = False
        with mock.patch("builtins.print"):
            for _ in range(sensors.SENSOR_FAULT_READS - 1):
                src.read()
            self.assertFalse(src.sensor_fault)
            src.read()
            self.assertTrue(src.sensor_fault)
            state["accel"] = True
            src.read()
        self.assertFalse(src.sensor_fault)

    def test_non_numeric_sensor_value_is_treated_as_missing(self):
        state = {}
        src = self.open(state)
        src.read()
        state["accel_values"] = ["rusak", 0, 0]
        with mock.patch("builtins.print"):
            self.assertFalse(src.read().accel_fresh)


class SimulatorTests(unittest.TestCase):
    def test_simulator_samples_are_fresh(self):
        s = sensors.Simulator("still").read()
        self.assertTrue(s.accel_fresh and s.gyro_fresh)


if __name__ == "__main__":
    unittest.main()
