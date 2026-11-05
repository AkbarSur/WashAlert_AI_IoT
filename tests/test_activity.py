"""Sumber aktivitas: aturan, model, fallback, smoothing, dan pemilihan mode."""
import glob
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from nodes.detector_service.activity import ModelActivitySource, RuleActivitySource, make_activity_source
from nodes.detector_service.inference import ActivityPrediction
from nodes.detector_service.rules import Config, WasherDetector
from shared.features import telemetry_extra
from shared.messages import Telemetry

CFG = Config(start_s=2, done_s=4, remind_s=20, spin_windows=3)
SYN_MODEL = (glob.glob("models/development/SYNTHETIC_*") or [None])[0]  # artefak dapat dibangun ulang, lihat ml_training_guide


def window():
    return {"window_s": 2.0, "n_samples": 5, "actual_hz": 2.0, "stale_count": 0, "acc_dyn_rms": 0.5, "acc_mag_ptp": 1.0, "gyro_rms": 0.1, "gyro_max": 0.2}


def reading(seq=0, rms=0.5, rot=0.1, v2=True, fault=False, t=1000):
    return Telemetry("edge1", "b", seq, t, rms, rot, telemetry_extra(window(), fault) if v2 else None)


class FakeModel:
    def __init__(self, prediction=None):
        self.metadata = {"window": {"aggregate_s": 30.0, "min_windows": 1, "min_coverage_s": 0.0}, "smoothing_n": 1}
        self.prediction = prediction or ActivityPrediction(True, "SPIN", {"SPIN": .9}, .9, model_version="m")
        self.calls = 0

    def predict(self, features):
        self.calls += 1
        return self.prediction


class RuleSource(unittest.TestCase):
    def setUp(self):
        self.s = RuleActivitySource(CFG)

    def test_single_bump_does_not_start(self):
        e = self.s.estimate(reading(rms=5), 0, "IDLE", 1.0)
        self.assertEqual(e.activity, "IDLE")
        self.assertEqual(e.source, "rule")

    def test_two_of_three_windows_start(self):
        self.s.estimate(reading(rms=.5), 0, "IDLE", .5)
        self.assertEqual(self.s.estimate(reading(rms=.5), 1, "IDLE", .5).activity, "WASHING")

    def test_hysteresis_band_stays_active(self):
        self.assertEqual(self.s.estimate(reading(rms=.2, rot=0), 0, "WASHING", .2).activity, "WASHING")

    def test_rotation_needs_consecutive_windows(self):
        acts = [self.s.estimate(reading(rms=.5, rot=.6), i, "WASHING", .5).activity for i in range(3)]
        self.assertEqual(acts, ["WASHING", "WASHING", "SPIN"])

    def test_rotation_streak_broken_by_stillness(self):
        for i in range(2):
            self.s.estimate(reading(rms=.5, rot=.6), i, "WASHING", .5)
        self.s.estimate(reading(rms=0, rot=0), 3, "WASHING", 0)
        self.assertEqual(self.s.estimate(reading(rms=.5, rot=.6), 4, "WASHING", .5).activity, "WASHING")


class ModelSource(unittest.TestCase):
    def make(self, prediction=None, allow_fallback=True):
        return ModelActivitySource(FakeModel(prediction), CFG, allow_fallback)

    def test_model_used_when_confident(self):
        e = self.make().estimate(reading(rms=0, rot=0), 1000, "WASHING", 0)
        self.assertEqual((e.activity, e.source, e.probability), ("SPIN", "model", .9))

    def test_v1_telemetry_falls_back_visibly(self):
        s = self.make()
        e = s.estimate(reading(rms=0, v2=False), 1000, "WASHING", 0)
        self.assertEqual((e.activity, e.source, e.reason), ("IDLE", "rule_fallback", "missing_features"))
        self.assertEqual(s.model.calls, 0)

    def test_sensor_fault_gives_unknown(self):
        e = self.make().estimate(reading(rms=0, fault=True), 1000, "WASHING", 0)
        self.assertEqual((e.activity, e.source, e.reason), ("UNKNOWN", "none", "sensor_fault"))

    def test_low_probability_uses_rule(self):
        p = ActivityPrediction(True, "SPIN", {"SPIN": .4}, .4, low_probability=True, reason="low_probability")
        e = self.make(p).estimate(reading(rms=0), 1000, "WASHING", 0)
        self.assertEqual((e.activity, e.source, e.probability), ("IDLE", "rule_low_probability", .4))

    def test_out_of_range_uses_rule(self):
        p = ActivityPrediction(True, "SPIN", {"SPIN": .9}, .9, out_of_range_features=("x_mean",), reason="out_of_training_range")
        e = self.make(p).estimate(reading(rms=0), 1000, "WASHING", 0)
        self.assertEqual((e.source, e.reason), ("rule_fallback", "out_of_training_range"))

    def test_incomplete_window(self):
        s = self.make()
        s.model.metadata  # jendela lengkap perlu minimal 3
        s.buffer.config = type(s.buffer.config)(30.0, 3, 20.0)
        self.assertEqual(s.estimate(reading(rms=0), 1000, "WASHING", 0).reason, "incomplete_window")

    def test_repeated_prediction_error_disables_model(self):
        s = self.make(ActivityPrediction(False, reason="prediction_error: x"))
        for i in range(5):
            s.estimate(reading(seq=i, rms=0), 1000 + i * 2000, "WASHING", 0)
        calls = s.model.calls
        e = s.estimate(reading(seq=6, rms=0), 30000, "WASHING", 0)
        self.assertEqual(e.reason, "prediction_error")
        self.assertEqual(s.model.calls, calls)

    def test_smoothing_rejects_single_flip(self):
        s = self.make()
        s.votes = type(s.votes)(maxlen=5)
        out = []
        for i, a in enumerate(["WASHING", "WASHING", "WASHING", "SPIN", "WASHING"]):
            s.model.prediction = ActivityPrediction(True, a, {a: .9}, .9)
            out.append(s.estimate(reading(seq=i, rms=0), 1000 + i * 2000, "WASHING", 0).activity)
        self.assertEqual(out, ["WASHING"] * 5)

    def test_ml_only_never_uses_rule(self):
        s = self.make(ActivityPrediction(True, "SPIN", {"SPIN": .2}, .2, low_probability=True, reason="low_probability"), allow_fallback=False)
        self.assertEqual(s.estimate(reading(rms=0), 1000, "WASHING", 0).source, "model")
        e = s.estimate(reading(seq=1, rms=0, v2=False), 3000, "WASHING", 0)
        self.assertEqual((e.source, e.activity, e.reason), ("none", "UNKNOWN", "missing_features"))

    def test_unexpected_label_never_reaches_fsm(self):
        s = self.make(ActivityPrediction(True, "DONE", {"DONE": .9}, .9))
        e = s.estimate(reading(rms=0), 1000, "WASHING", 0)
        self.assertEqual((e.activity, e.source, e.reason), ("IDLE", "rule_fallback", "unexpected_label"))

    def test_latency_measured(self):
        s = self.make()
        s.estimate(reading(rms=0), 1000, "WASHING", 0)
        self.assertGreaterEqual(s.last_latency_ms, 0)

    def test_sensor_fault_cannot_cause_false_done(self):
        for allow in (True, False):
            cfg = Config(start_s=2, done_s=2, remind_s=20)
            d = WasherDetector(cfg, activity_source=ModelActivitySource(FakeModel(ActivityPrediction(True, "IDLE", {"IDLE": 1.0}, 1.0)), cfg, allow))
            d.state, d.started_at = "WASHING", 1000
            for i in range(8):
                t = 2000 + i * 1000
                r = d.accept(reading(seq=i, rms=0, fault=True, t=t), t)
            self.assertEqual((r.status, r.activity), ("WASHING", "UNKNOWN"))
            self.assertIsNone(d.still_since)

    def test_rule_only_sensor_fault_cannot_cause_false_done(self):
        d = WasherDetector(Config(start_s=2, done_s=2, remind_s=20))
        d.state, d.started_at = "WASHING", 1000
        for i in range(8):
            r = d.accept(reading(seq=i, rms=0, fault=True, t=2000 + i * 1000), 2000 + i * 1000)
        self.assertEqual(r.status, "WASHING")

    def test_model_failure_disables_and_status_can_say_so(self):
        s = self.make(ActivityPrediction(False, reason="prediction_error: x"), allow_fallback=False)
        for i in range(5):
            e = s.estimate(reading(seq=i, rms=0), 1000 + i * 2000, "WASHING", 0)
        self.assertEqual(s.disabled_reason, "prediction_error")
        self.assertEqual(e.source, "rule_fallback")

    def test_probability_never_decides_done_directly(self):
        # Model yakin IDLE hanya memberi aktivitas; DONE tetap butuh durasi FSM.
        d = WasherDetector(CFG, activity_source=self.make(ActivityPrediction(True, "IDLE", {"IDLE": 1.0}, 1.0)))
        d.state, d.started_at = "WASHING", 0
        result = d.accept(reading(rms=0, t=1000), 1000)
        self.assertEqual(result.status, "WASHING")
        self.assertFalse(result.alert)
        self.assertEqual(result.activity_source, "model")


class Requirements(unittest.TestCase):
    def test_offset_does_not_block_done_in_hybrid(self):
        # motion_rms tinggi karena offset kalibrasi; aturan melihatnya aktif, model melihat IDLE.
        cfg = Config(start_s=2, done_s=4, remind_s=20)
        d = WasherDetector(cfg, activity_source=ModelActivitySource(FakeModel(ActivityPrediction(True, "IDLE", {"IDLE": 1.0}, 1.0)), cfg))
        d.state, d.started_at = "WASHING", 1000
        results = [d.accept(reading(seq=i, rms=.5, t=2000 + i * 1000), 2000 + i * 1000) for i in range(6)]
        self.assertEqual(results[-1].status, "DONE")

    def test_single_bump_ignored_at_any_period(self):
        cfg = Config(start_s=2, done_s=4, remind_s=20)
        for period in (1000, 5000, 10000):
            d = WasherDetector(cfg)
            statuses = [d.accept(reading(seq=i, rms=5.0 if i == 2 else 0.0, t=1000 + i * period), 1000 + i * period).status for i in range(8)]
            self.assertEqual(set(statuses), {"IDLE"}, period)

    def test_core_runs_without_ml_or_mqtt_packages(self):
        code = """
import sys
for name in ("sklearn", "numpy", "joblib", "paho", "paho.mqtt"):
    sys.modules[name] = None
from nodes.detector_service.rules import Config, WasherDetector
from shared.messages import Telemetry
d = WasherDetector(Config(0, 1, 60))
r = d.accept(Telemetry("edge1", "b", 0, 1000, 1.0, 0.0), 1000)
assert r.activity_source == "rule"
"""
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_payloads_hold_no_personal_fields(self):
        from nodes.detector_service.main import DetectorService
        client = mock.Mock()
        service = DetectorService(client, WasherDetector(CFG), {"detection_mode": "RULE_ONLY", "effective_mode": "RULE_ONLY"}, log=lambda *a: None)
        service.publish_status("IDLE", "x")
        text = client.publish.call_args.args[1].lower()
        for word in ("operator", "password", "token", "email", "@"):
            self.assertNotIn(word, text)


class Modes(unittest.TestCase):
    def test_rule_only_default_without_model(self):
        s, info = make_activity_source("RULE_ONLY", None, CFG)
        self.assertIsInstance(s, RuleActivitySource)
        self.assertEqual(info, {"detection_mode": "RULE_ONLY", "effective_mode": "RULE_ONLY", "model_status": "not_configured"})

    @unittest.skipUnless(SYN_MODEL, "model sintetis belum dibangun")
    def test_ml_only_runs_without_window_fallback(self):
        s, info = make_activity_source("ML_ONLY", SYN_MODEL, CFG, True)
        self.assertFalse(s.allow_fallback)
        self.assertEqual((info["effective_mode"], info["model_status"]), ("ML_ONLY", "active"))

    def test_ml_only_missing_model_reports_rule_only(self):
        _, info = make_activity_source("ML_ONLY", None, CFG)
        self.assertEqual((info["detection_mode"], info["effective_mode"], info["model_status"]), ("ML_ONLY", "RULE_ONLY", "unavailable"))

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            make_activity_source("AI", None, CFG)

    def test_hybrid_without_path_falls_back_visibly(self):
        s, info = make_activity_source("HYBRID", None, CFG)
        self.assertIsInstance(s, RuleActivitySource)
        self.assertEqual((info["effective_mode"], info["fallback_reason"]), ("RULE_ONLY", "model_missing"))

    def test_hybrid_missing_dir(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(make_activity_source("HYBRID", d, CFG)[1]["fallback_reason"], "model_missing")

    @unittest.skipUnless(SYN_MODEL, "model sintetis belum dibangun")
    def test_synthetic_model_blocked_by_default(self):
        _, info = make_activity_source("HYBRID", SYN_MODEL, CFG)
        self.assertEqual((info["effective_mode"], info["fallback_reason"]), ("RULE_ONLY", "synthetic_not_allowed"))

    @unittest.skipUnless(SYN_MODEL, "model sintetis belum dibangun")
    def test_synthetic_model_explicit_is_labelled(self):
        s, info = make_activity_source("HYBRID", SYN_MODEL, CFG, allow_synthetic=True)
        self.assertIsInstance(s, ModelActivitySource)
        self.assertEqual((info["effective_mode"], info["model_data_kind"], info["probability_calibrated"]), ("HYBRID", "synthetic", False))

    @unittest.skipUnless(SYN_MODEL, "model sintetis belum dibangun")
    def test_missing_dependency_falls_back(self):
        with mock.patch("nodes.detector_service.activity.try_load", return_value=(None, "dependency_missing")):
            self.assertEqual(make_activity_source("HYBRID", SYN_MODEL, CFG, True)[1]["fallback_reason"], "dependency_missing")


if __name__ == "__main__":
    unittest.main()
