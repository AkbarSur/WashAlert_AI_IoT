"""Alert: format, validasi HP B, dedupe, retained state, dan layanan detector dengan klien tiruan."""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from nodes.detector_service import state_store
from nodes.detector_service.main import DetectorService, build_detector
from nodes.detector_service.rules import Config, Decision, WasherDetector
from shared.edge_runner import AlertReceiver
from shared.messages import Telemetry, alert_json, parse_alert, status_json

NOW = 2_000_000_000_000


def alert(aid="a1", at=NOW, valid=660, kind="completed_after_spin"):
    return alert_json(5.0, "selesai", at, aid, kind, False, valid)


class Format(unittest.TestCase):
    def test_keeps_legacy_fields(self):
        body = json.loads(alert())
        for key in ("event", "run_minutes", "reason", "detected_at_ms"):
            self.assertIn(key, body)
        self.assertEqual(body["event"], "laundry_done")

    def test_legacy_four_field_alert_accepted(self):
        legacy = json.dumps({"event": "laundry_done", "run_minutes": 1, "reason": "x", "detected_at_ms": NOW})
        self.assertEqual(parse_alert(legacy, NOW)["event"], "laundry_done")

    def test_rejects_bad(self):
        for bad in ("[]", "{}", '{"event":"x","reason":"r","run_minutes":-1,"detected_at_ms":1}',
                    '{"event":"x","reason":"r","run_minutes":1,"detected_at_ms":true}'):
            with self.assertRaises(ValueError):
                parse_alert(bad, NOW)

    def test_rejects_expired(self):
        with self.assertRaises(ValueError):
            parse_alert(alert(at=NOW - 661_000), NOW)

    def test_status_without_extra_unchanged(self):
        self.assertNotIn("detection_mode", json.loads(status_json("IDLE", "r", True)))


class Receiver(unittest.TestCase):
    def setUp(self):
        self.rung, self.cleared = [], []
        self.r = AlertReceiver(self.rung.append, lambda: self.cleared.append(1), clock=lambda: NOW / 1000, log=lambda *a: None, worker=False)

    def test_dedupes_same_id(self):
        self.assertTrue(self.r.handle_alert(alert()))
        self.assertFalse(self.r.handle_alert(alert()))
        self.assertEqual(len(self.rung), 1)

    def test_reminder_with_new_id_rings(self):
        self.r.handle_alert(alert("a1"))
        self.r.handle_alert(alert("a2"))
        self.assertEqual(len(self.rung), 2)

    def test_malformed_ignored(self):
        self.assertFalse(self.r.handle_alert(b"bukan json"))
        self.assertFalse(self.r.handle_state(b"bukan json"))
        self.assertEqual(self.rung, [])

    def test_retained_state_catches_up_once(self):
        state = json.dumps({**json.loads(alert()), "active": True})
        self.r.handle_state(state)
        self.r.handle_alert(alert())
        self.assertEqual(len(self.rung), 1)

    def test_expired_retained_state_silent(self):
        self.r.handle_state(json.dumps({**json.loads(alert(at=NOW - 10**7)), "active": True}))
        self.assertEqual(self.rung, [])

    def test_inactive_clears_only_after_active(self):
        off = json.dumps({"active": False, "updated_at_ms": NOW})
        self.r.handle_state(off)
        self.assertEqual(self.cleared, [])
        self.r.handle_state(json.dumps({**json.loads(alert()), "active": True}))
        self.r.handle_state(off)
        self.assertEqual(self.cleared, [1])

    def test_alarm_failure_does_not_escape(self):
        def boom(_):
            raise RuntimeError("x")
        r = AlertReceiver(boom, clock=lambda: NOW / 1000, log=lambda *a: None, worker=False)
        self.assertTrue(r.handle_alert(alert()))

    def test_slow_alarm_does_not_block_mqtt_thread(self):
        r = AlertReceiver(lambda a: time.sleep(1), clock=lambda: NOW / 1000, log=lambda *a: None)
        start = time.time()
        r.handle_alert(alert())
        self.assertLess(time.time() - start, 0.5)


class Service(unittest.TestCase):
    def setUp(self):
        self.client = mock.Mock()
        cfg = Config(0, 1, 300, sensor_lost_s=5)
        self.d = WasherDetector(cfg)
        self.clock = [NOW / 1000]
        self.s = DetectorService(self.client, self.d, {"detection_mode": "RULE_ONLY", "effective_mode": "RULE_ONLY"},
                                 clock=lambda: self.clock[0], log=lambda *a: None)

    def sent(self, name):
        return [json.loads(c.args[1]) for c in self.client.publish.call_args_list if c.args[0].endswith("/" + name)]

    def msg(self, device, seq, rms):
        return mock.Mock(topic=f"{self.s.telemetry_topic.replace('+', device)}", payload=Telemetry(device, "b", seq, self.s.now_ms(), rms, 0.0).to_json().encode())

    def finish(self):
        self.d.advance("WASHING", self.s.now_ms())
        self.s.on_message(None, None, self.msg("edge1", 0, 5))
        self.s.on_message(None, None, self.msg("edge1", 1, 5))
        for i in range(2, 9):
            self.clock[0] += 1
            self.s.on_message(None, None, self.msg("edge1", i, 0))
        self.assertEqual(self.d.state, "DONE")

    def test_status_carries_mode_and_sensor(self):
        self.s.on_message(None, None, self.msg("edge1", 0, 0))
        st = self.sent("status")[-1]
        self.assertEqual((st["detection_mode"], st["effective_mode"], st["activity_source"]), ("RULE_ONLY", "RULE_ONLY", "rule"))
        self.assertEqual(st["rejected"], {"stale": 0, "replay": 0, "schema": 0})
        self.assertFalse(st["sensor"]["lost"])

    def test_done_publishes_alert_and_retained_state(self):
        self.finish()
        a = self.sent("alerts")[-1]
        st = self.sent("alert_state")[-1]
        self.assertTrue(st["active"])
        self.assertEqual(st["alert_id"], a["alert_id"])
        self.assertEqual(a["valid_for_s"], 660)
        retained = [c for c in self.client.publish.call_args_list if c.args[0].endswith("/alert_state")][-1]
        self.assertTrue(retained.kwargs["retain"])

    def test_ack_clears_state(self):
        self.finish()
        self.s.on_message(None, None, self.msg("edge2", 0, 5))
        self.assertFalse(self.sent("alert_state")[-1]["active"])

    def test_disarm_clears_state(self):
        self.finish()
        self.s.handle_control(b"DISARM")
        self.assertFalse(self.sent("alert_state")[-1]["active"])
        self.assertEqual(self.sent("status")[-1]["status"], "DISARMED")

    def test_arm_reports_true_state(self):
        self.s.handle_control(b"ARM")
        self.assertEqual(self.sent("status")[-1]["status"], "IDLE")

    def test_correction_clear_precedes_alert(self):
        self.s.apply(Decision("DONE", "x", alert=True, alert_kind="completed_after_spin"))
        self.client.publish.reset_mock()
        self.s.apply(Decision("WASHING", "k", alert=True, alert_kind="correction", clear_alert=True))
        topics = [c.args[0].rsplit("/", 1)[1] for c in self.client.publish.call_args_list]
        self.assertLess(topics.index("alert_state"), topics.index("alerts"))

    def test_bad_payload_counted_not_fatal(self):
        self.s.on_message(None, None, mock.Mock(topic=self.s.telemetry_topic.replace("+", "edge1"), payload=b"x"))
        self.assertEqual(self.s.rejected_schema, 1)

    def test_topic_device_mismatch_rejected(self):
        m = self.msg("edge1", 0, 0)
        m.topic = self.s.telemetry_topic.replace("+", "edge2")
        self.s.on_message(None, None, m)
        self.assertEqual(self.s.rejected_schema, 1)

    def test_replay_counted_and_status_rate_limited(self):
        self.s.on_message(None, None, self.msg("edge1", 0, 0))
        self.client.publish.reset_mock()
        for _ in range(5):
            self.s.on_message(None, None, self.msg("edge1", 0, 0))
        self.assertEqual(self.d.rejected["replay"], 5)
        self.assertLessEqual(len(self.sent("status")), 1)

    def test_exception_in_handler_does_not_propagate(self):
        self.d.accept = mock.Mock(side_effect=RuntimeError("x"))
        self.s.on_message(None, None, self.msg("edge1", 0, 0))

    def test_tick_reminder_published(self):
        self.finish()
        self.client.publish.reset_mock()
        self.clock[0] += 301
        self.d.last_edge1_at = self.s.now_ms()
        self.s.tick()
        self.assertTrue(self.sent("alerts")[-1]["is_reminder"])


class Persistence(unittest.TestCase):
    def make(self, path, clock):
        client = mock.Mock()
        s = DetectorService(client, WasherDetector(Config(0, 1, 300)), {"detection_mode": "RULE_ONLY", "effective_mode": "RULE_ONLY"},
                            clock=lambda: clock[0], log=lambda *a: None, state_path=path)
        s.restore_state()
        return s, client

    def test_done_survives_restart_and_reminder_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, clock = f"{tmp}/s.json", [NOW / 1000]
            s, _ = self.make(path, clock)
            s.detector.state, s.detector.started_at, s.detector.finished_at = "DONE", NOW - 60_000, NOW - 1000
            s.detector.last_alert_at, s.detector.alert_kind = NOW, "completed_after_spin"
            s.active_alert = {"active": True, "alert_id": "a"}
            s.persist()
            clock[0] += 400
            s2, client = self.make(path, clock)
            self.assertEqual(s2.detector.state, "DONE")
            s2.on_connect(client, None, None, mock.Mock(is_failure=False), None)
            first = json.loads(client.publish.call_args_list[0].args[1])
            self.assertEqual(first["status"], "DONE")
            s2.tick()
            kinds = [json.loads(c.args[1]).get("is_reminder") for c in client.publish.call_args_list if c.args[0].endswith("/alerts")]
            self.assertEqual(kinds, [True])

    def test_corrupt_or_old_state_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/s.json"
            with open(path, "w") as f:
                f.write("{rusak")
            s, _ = self.make(path, [NOW / 1000])
            self.assertEqual(s.detector.state, "IDLE")
            state_store.save(path, {"detector": {"state": "DONE"}}, NOW - 10**9)
            self.assertEqual(self.make(path, [NOW / 1000])[0].detector.state, "IDLE")
            state_store.save(path, {"detector": {"state": "RUSAK", "armed": True}}, NOW)
            self.assertEqual(self.make(path, [NOW / 1000])[0].detector.state, "IDLE")

    def test_runtime_model_failure_visible_in_status(self):
        client = mock.Mock()
        d = WasherDetector(Config(0, 1, 300))
        d.source.disabled_reason = "prediction_error"
        s = DetectorService(client, d, {"detection_mode": "HYBRID", "effective_mode": "HYBRID", "model_status": "active"}, clock=lambda: NOW / 1000, log=lambda *a: None)
        s.publish_status("IDLE", "x")
        body = json.loads(client.publish.call_args.args[1])
        self.assertEqual((body["detection_mode"], body["effective_mode"], body["model_status"], body["fallback_reason"]), ("HYBRID", "RULE_ONLY", "failed", "prediction_error"))

    def test_structured_event_is_json(self):
        lines = []
        s = DetectorService(mock.Mock(), WasherDetector(Config(0, 1, 300)), {"detection_mode": "RULE_ONLY", "effective_mode": "RULE_ONLY"}, clock=lambda: NOW / 1000, log=lines.append)
        s.event("startup", detection_mode="RULE_ONLY")
        self.assertEqual(json.loads(lines[0].removeprefix("[EVENT] "))["event"], "startup")


class Reconnect(unittest.TestCase):
    def test_reconnect_reports_true_state(self):
        client = mock.Mock()
        d = WasherDetector(Config(0, 1, 300))
        s = DetectorService(client, d, {"detection_mode": "RULE_ONLY", "effective_mode": "RULE_ONLY"}, clock=lambda: NOW / 1000, log=lambda *a: None)
        ok = mock.Mock(is_failure=False)
        s.on_connect(client, None, None, ok, None)
        self.assertEqual(json.loads(client.publish.call_args_list[0].args[1])["status"], "ONLINE")
        d.state, d.started_at = "WASHING", NOW - 60_000
        client.publish.reset_mock()
        s.on_connect(client, None, None, ok, None)
        body = json.loads(client.publish.call_args_list[0].args[1])
        self.assertEqual((body["status"], body["run_minutes"]), ("WASHING", 1.0))


class Build(unittest.TestCase):
    def test_default_is_rule_only(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(build_detector()[1]["effective_mode"], "RULE_ONLY")

    def test_invalid_mode_raises(self):
        with mock.patch.dict(os.environ, {"DETECTION_MODE": "AI"}, clear=True), self.assertRaises(ValueError):
            build_detector()


if __name__ == "__main__":
    unittest.main()
