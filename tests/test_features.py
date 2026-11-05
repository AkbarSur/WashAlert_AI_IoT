"""FR dan DML fitur. Sinyal buatan dengan hasil yang diketahui."""
import math
import unittest

from shared.features import (ALL_FEATURE_COLUMNS, AggregateBuffer, InvalidWindow, WindowConfig,
                             compute_window_features, feature_names, telemetry_extra, window_usable)
from shared.processing import SensorSample, extract_features


def sine(ax=0.0, az=0.0, offset=0.0, n=1000, fs=1000.0, f=20.0, gyro=0.0):
    return [SensorSample(i / fs, (ax * math.sin(2 * math.pi * f * i / fs), 0.0,
                                  9.81 + offset + az * math.sin(2 * math.pi * f * i / fs)), (gyro, 0.0, 0.0))
            for i in range(n)]


def window(**kw):
    base = dict(motion_rms=0.1, rotation_rad=0.1, acc_dyn_rms=0.2, acc_mag_ptp=0.3, gyro_rms=0.05, gyro_max=0.08,
                window_s=4.0, n_samples=5, actual_hz=1.0, stale_count=0)
    base.update(kw)
    return base


class WindowFeatureTests(unittest.TestCase):
    def test_legacy_features_unchanged(self):
        samples = sine(az=1.0)
        legacy = extract_features(samples)
        w = compute_window_features(samples)
        self.assertEqual((w["motion_rms"], w["rotation_rad"]), (legacy.motion_rms, legacy.rotation_rad))

    def test_acc_dyn_rms_sees_horizontal_and_vertical_equally(self):
        h = compute_window_features(sine(ax=1.0))
        v = compute_window_features(sine(az=1.0))
        self.assertAlmostEqual(h["acc_dyn_rms"], 1 / math.sqrt(2), places=3)
        self.assertLessEqual(abs(h["acc_dyn_rms"] - v["acc_dyn_rms"]) / v["acc_dyn_rms"], 0.05)
        self.assertLess(h["motion_rms"], 0.1)  # kelemahan fitur lama yang diatasi

    def test_offset_does_not_change_acc_dyn_rms(self):
        a = compute_window_features(sine(ax=1.0))["acc_dyn_rms"]
        b = compute_window_features(sine(ax=1.0, offset=0.3))["acc_dyn_rms"]
        self.assertLessEqual(abs(a - b) / a, 0.01)

    def test_gyro_rms_independent_of_window_length(self):
        short = compute_window_features(sine(n=500, gyro=0.2))
        long = compute_window_features(sine(n=1000, gyro=0.2))
        self.assertEqual(short["gyro_rms"], long["gyro_rms"])
        self.assertAlmostEqual(short["gyro_rms"], 0.2, places=6)
        self.assertGreater(long["rotation_rad"], short["rotation_rad"])

    def test_actual_rate_from_timestamps_not_nominal(self):
        samples = [SensorSample(t, (0, 0, 9.81), (0, 0, 0)) for t in (0, 0.5, 1.0, 1.5, 2.0)]
        w = compute_window_features(samples)
        self.assertEqual((w["window_s"], w["n_samples"], w["actual_hz"]), (2.0, 5, 2.0))

    def test_irregular_sampling_uses_real_duration(self):
        samples = [SensorSample(t, (0, 0, 9.81), (0, 0, 0)) for t in (0, 0.1, 3.0, 3.1)]
        self.assertAlmostEqual(compute_window_features(samples)["actual_hz"], 3 / 3.1, places=3)

    def test_stale_samples_counted(self):
        samples = [SensorSample(i, (0, 0, 9.81), (0, 0, 0), gyro_fresh=i % 2 == 0) for i in range(5)]
        self.assertEqual(compute_window_features(samples)["stale_count"], 2)

    def test_insufficient_samples_rejected(self):
        with self.assertRaises(InvalidWindow):
            compute_window_features(sine(n=1))

    def test_nan_and_infinity_rejected(self):
        for bad in (float("nan"), float("inf")):
            samples = sine(n=5) + [SensorSample(9.0, (bad, 0, 9.81), (0, 0, 0))]
            with self.assertRaises(InvalidWindow):
                compute_window_features(samples)

    def test_backward_timestamp_gives_no_negative_values(self):
        samples = [SensorSample(t, (0, 0, 9.81), (1, 0, 0)) for t in (5.0, 4.0, 3.0)]
        w = compute_window_features(samples)
        self.assertEqual((w["window_s"], w["actual_hz"], w["rotation_rad"]), (0.0, 0.0, 0.0))
        self.assertFalse(window_usable(w))

    def test_deterministic(self):
        self.assertEqual(compute_window_features(sine(ax=1)), compute_window_features(sine(ax=1)))

    def test_telemetry_extra_contains_no_label_or_identity(self):
        extra = telemetry_extra(compute_window_features(sine(n=10)))
        self.assertEqual(extra["schema_version"], 2)
        self.assertFalse({"label", "session_id", "machine_id"} & set(extra))


class AggregateTests(unittest.TestCase):
    CFG = WindowConfig(aggregate_s=30, min_windows=3, min_coverage_s=20)

    def filled(self, period=5, count=10):
        b = AggregateBuffer(self.CFG)
        for i in range(count):
            b.add(1000 + i * period * 1000, window(window_s=4.0, acc_dyn_rms=float(i)))
        return b

    def test_not_ready_with_few_windows(self):
        b = AggregateBuffer(self.CFG)
        b.add(1000, window())
        b.add(6000, window())
        self.assertIsNone(b.aggregate())

    def test_not_ready_when_coverage_too_short(self):
        b = AggregateBuffer(self.CFG)
        for i in range(5):
            b.add(1000 + i * 1000, window(window_s=1.0))
        self.assertLess(b.coverage_s(), 20)
        self.assertIsNone(b.aggregate())

    def test_boundary_window_excluded_exactly_at_limit(self):
        b = AggregateBuffer(self.CFG)
        b.add(0 + 1000, window())
        b.add(31000, window())  # tepat 30 detik setelah yang pertama: yang pertama keluar
        self.assertEqual(len(b.items), 1)

    def test_statistics_correct(self):
        b = AggregateBuffer(self.CFG)
        for i, v in enumerate((1.0, 2.0, 3.0)):
            b.add(1000 + i * 10000, window(acc_dyn_rms=v))
        out = b.aggregate()
        self.assertEqual(out["acc_dyn_rms_mean"], 2.0)
        self.assertEqual(out["acc_dyn_rms_max"], 3.0)
        self.assertAlmostEqual(out["acc_dyn_rms_std"], math.sqrt(2 / 3), places=5)

    def test_uses_only_past_windows(self):
        d = self.filled(count=8)
        before = d.aggregate()
        self.assertEqual(before, self.filled(count=8).aggregate())
        snapshot = dict(before)
        d.add(d.items[-1][0] + 1000, window(acc_dyn_rms=999.0))  # jendela berikutnya
        self.assertEqual(snapshot, before)                       # hasil sebelumnya tidak berubah
        self.assertNotEqual(d.aggregate()["acc_dyn_rms_max"], before["acc_dyn_rms_max"])

    def test_out_of_order_window_rejected(self):
        b = AggregateBuffer(self.CFG)
        self.assertTrue(b.add(5000, window()))
        self.assertFalse(b.add(4000, window()))
        self.assertFalse(b.add(5000, window()))

    def test_stale_window_not_used(self):
        b = AggregateBuffer(self.CFG)
        self.assertFalse(b.add(1000, window(stale_count=3)))  # fresh 40%
        self.assertTrue(b.add(2000, window(stale_count=2)))   # fresh 60%

    def test_gap_ages_out_old_windows(self):
        b = self.filled(count=8)
        b.add(10**7, window())
        self.assertEqual(len(b.items), 1)
        self.assertIsNone(b.aggregate())

    def test_feature_order_fixed(self):
        self.assertEqual(feature_names("F2")[0:3], ("acc_dyn_rms_mean", "acc_dyn_rms_std", "acc_dyn_rms_max"))
        self.assertEqual(len(feature_names("F1")), 6)
        self.assertEqual(len(feature_names("F2")), 12)
        self.assertEqual(len(ALL_FEATURE_COLUMNS), 18)
        self.assertEqual(set(self.filled().aggregate()), set(ALL_FEATURE_COLUMNS))


if __name__ == "__main__":
    unittest.main()
