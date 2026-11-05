"""Aturan siklus baru. Waktu disuntikkan lewat advance/tick sehingga deterministik."""
import os
import unittest
from unittest import mock

from nodes.detector_service.rules import Config, WasherDetector
from shared.messages import Telemetry

S = 1000
CFG = Config(start_s=60, done_s=120, remind_s=300, min_run_s=600, done_nospin_s=240, ack_windows=2, sensor_lost_s=60)


def running(cfg=CFG, spin=True, minutes=20):
    d = WasherDetector(cfg)
    d.advance("WASHING", S)
    d.advance("WASHING", 61 * S)
    assert d.state == "WASHING"
    d.advance("SPIN" if spin else "WASHING", minutes * 60 * S)
    return d, minutes * 60 * S


def edge(device, seq, now, rms=0.0):
    return Telemetry(device, "b", seq, now, rms, 0.0)


class Cycle(unittest.TestCase):
    def test_short_run_never_alerts(self):
        d = WasherDetector(CFG)
        d.advance("WASHING", S)
        d.advance("WASHING", 61 * S)
        d.advance("IDLE", 120 * S)
        r = d.advance("IDLE", 1000 * S)
        self.assertFalse(r.alert)
        self.assertEqual(r.status, "WASHING")

    def test_after_spin_uses_done_s(self):
        d, t = running()
        d.advance("IDLE", t)
        self.assertFalse(d.advance("IDLE", t + 119 * S).alert)
        r = d.advance("IDLE", t + 120 * S)
        self.assertTrue(r.alert)
        self.assertEqual((r.status, r.alert_kind), ("DONE", "completed_after_spin"))

    def test_without_spin_waits_longer_and_says_so(self):
        d, t = running(spin=False)
        d.advance("IDLE", t)
        self.assertFalse(d.advance("IDLE", t + 120 * S).alert)
        r = d.advance("IDLE", t + 240 * S)
        self.assertEqual(r.alert_kind, "stopped_without_spin")

    def test_pause_shorter_than_limit_is_not_done(self):
        d, t = running()
        d.advance("IDLE", t)
        d.advance("IDLE", t + 100 * S)
        d.advance("WASHING", t + 110 * S)
        d.advance("IDLE", t + 120 * S)
        self.assertFalse(d.advance("IDLE", t + 200 * S).alert)

    def test_finished_time_excludes_wait(self):
        d, t = running()
        d.advance("IDLE", t)
        r = d.advance("IDLE", t + 120 * S)
        self.assertEqual(r.run_minutes, 19.98)

    def test_correction_after_false_done(self):
        d, t = running()
        d.advance("IDLE", t)
        d.advance("IDLE", t + 120 * S)
        d.advance("WASHING", t + 130 * S)
        r = d.advance("WASHING", t + 190 * S)
        self.assertEqual((r.status, r.alert_kind, r.alert, r.clear_alert), ("WASHING", "correction", True, True))
        self.assertIsNone(d.tick(t + 2000 * S))

    def test_brief_bump_in_done_is_not_correction(self):
        d, t = running()
        d.advance("IDLE", t)
        d.advance("IDLE", t + 120 * S)
        d.advance("WASHING", t + 130 * S)
        d.advance("IDLE", t + 140 * S)
        self.assertEqual(d.advance("WASHING", t + 200 * S).status, "DONE")

    def test_abandon_off_by_default_on_when_set(self):
        d = WasherDetector(CFG)
        self.assertIsNone(CFG.abandon_s)
        cfg = Config(60, 120, 300, min_run_s=600, abandon_s=300)
        d = WasherDetector(cfg)
        d.advance("WASHING", S)
        d.advance("WASHING", 61 * S)
        d.advance("IDLE", 120 * S)
        r = d.advance("IDLE", 420 * S)
        self.assertEqual(r.status, "IDLE")
        self.assertFalse(r.alert)


class Scenarios(unittest.TestCase):
    def test_idle_washing_spin_transitions(self):
        d = WasherDetector(CFG)
        self.assertEqual(d.advance("IDLE", S).status, "IDLE")
        d.advance("WASHING", 2 * S)
        self.assertEqual(d.advance("WASHING", 62 * S).status, "WASHING")
        self.assertEqual(d.advance("SPIN", 70 * S).status, "SPIN")

    def test_washing_pause_washing_and_spin_pause_spin(self):
        for phase in ("WASHING", "SPIN"):
            d, t = running(spin=phase == "SPIN")
            for off in (0, 60, 110):
                r = d.advance("IDLE", t + off * S)
                self.assertFalse(r.alert)
            r = d.advance(phase, t + 115 * S)
            self.assertEqual(r.status, phase)
            self.assertIsNone(d.still_since)

    def test_noisy_flips_do_not_finish(self):
        d, t = running()
        for i in range(60):
            r = d.advance("IDLE" if i % 2 else "WASHING", t + i * 30 * S)
            self.assertFalse(r.alert)

    def test_done_alert_not_duplicated(self):
        d, t = running()
        d.advance("IDLE", t)
        results = [d.advance("IDLE", t + (120 + i) * S) for i in range(100)]
        self.assertEqual(sum(r.alert for r in results), 1)

    def test_owner_absent_reminders_continue_without_duplicate(self):
        d, t = running()
        d.advance("IDLE", t)
        d.advance("IDLE", t + 120 * S)
        d.last_edge1_at = t + 3000 * S
        alerts = [d.advance("IDLE", t + (120 + i) * S).alert for i in range(1, 901)]
        self.assertEqual(sum(alerts), 3)

    def test_repeated_cycles(self):
        d = WasherDetector(CFG)
        t = S
        for _ in range(3):
            d.advance("WASHING", t)
            d.advance("WASHING", t + 60 * S)
            d.advance("SPIN", t + 700 * S)
            d.advance("IDLE", t + 701 * S)
            self.assertTrue(d.advance("IDLE", t + 821 * S).alert)
            d.accept(edge("edge2", int(t / S), t + 822 * S, 5), t + 822 * S)
            r = d.accept(edge("edge2", int(t / S) + 1, t + 822 * S, 5), t + 822 * S)
            self.assertEqual(r.status, "IDLE")
            t += 2000 * S

    def test_disarm_during_cycle_silences_and_resets(self):
        d, t = running()
        d.set_armed(False)
        r = d.accept(edge("edge1", 0, t + S, 5), t + S)
        self.assertEqual(r.status, "DISARMED")
        d.set_armed(True)
        self.assertEqual((d.state, d.started_at), ("IDLE", None))

    def test_stale_ack_rejected(self):
        d, t = running()
        d.advance("IDLE", t)
        d.advance("IDLE", t + 120 * S)
        r = d.accept(edge("edge2", 0, t, 5), t + 200 * S)
        self.assertEqual(r.status, "REJECTED_STALE")
        self.assertEqual(d.state, "DONE")

    def test_replayed_ack_counts_once(self):
        d, t = running()
        d.advance("IDLE", t)
        d.advance("IDLE", t + 120 * S)
        n = t + 121 * S
        d.accept(edge("edge2", 7, n, 5), n)
        self.assertEqual(d.accept(edge("edge2", 7, n, 5), n).status, "REJECTED_REPLAY")
        self.assertEqual(d.state, "DONE")

    def test_sequence_gap_accepted(self):
        d = WasherDetector(CFG)
        d.accept(edge("edge1", 1, S), S)
        self.assertEqual(d.accept(edge("edge1", 50, 2 * S), 2 * S).status, "IDLE")

    def test_unknown_activity_holds_timers(self):
        d, t = running()
        d.advance("IDLE", t)
        d.advance("UNKNOWN", t + 100 * S)
        self.assertFalse(d.advance("IDLE", t + 121 * S).alert)


class Tick(unittest.TestCase):
    def test_reminder_without_telemetry(self):
        d, t = running(cfg=Config(60, 120, 300, min_run_s=600))
        d.advance("IDLE", t)
        d.advance("IDLE", t + 120 * S)
        self.assertIsNone(d.tick(t + 200 * S))
        r = d.tick(t + 420 * S)
        self.assertTrue(r.alert and r.is_reminder)
        self.assertEqual(r.alert_kind, "completed_after_spin")
        self.assertIsNone(d.tick(t + 421 * S))

    def test_sensor_lost_mid_cycle_is_not_done(self):
        d = WasherDetector(CFG)
        d.accept(edge("edge1", 0, 0), 0)
        d.state, d.started_at = "WASHING", 0
        d.still_since = 0
        r = d.tick(61 * S)
        self.assertEqual((r.status, r.alert_kind), ("SENSOR_LOST", "sensor_lost"))
        self.assertIsNone(d.still_since)
        self.assertIsNone(d.tick(5000 * S))
        self.assertEqual(d.state, "WASHING")

    def test_data_returns_clears_lost(self):
        d = WasherDetector(CFG)
        d.accept(edge("edge1", 0, 0), 0)
        d.state, d.started_at = "WASHING", 0
        d.tick(61 * S)
        r = d.accept(edge("edge1", 1, 100 * S, rms=.5), 100 * S)
        self.assertFalse(d.sensor_lost)
        self.assertEqual(r.status, "WASHING")

    def test_lost_in_idle_keeps_idle_without_alert(self):
        d = WasherDetector(CFG)
        d.accept(edge("edge1", 0, 0), 0)
        r = d.tick(61 * S)
        self.assertEqual(r.status, "IDLE")
        self.assertFalse(r.alert)
        self.assertTrue(d.sensor_lost)

    def test_lost_in_done_stays_done_reminds_and_ack_works(self):
        d, t = running()
        d.last_edge1_at = t
        d.advance("IDLE", t)
        d.advance("IDLE", t + 50 * S)
        d.sensor_lost = False
        d.advance("IDLE", t + 120 * S)
        d.last_edge1_at = t + 120 * S
        self.assertEqual(d.tick(t + 200 * S).status, "DONE")
        self.assertTrue(d.tick(t + 420 * S).alert)
        d.accept(edge("edge2", 0, t + 430 * S, rms=5), t + 430 * S)
        self.assertEqual(d.accept(edge("edge2", 1, t + 432 * S, rms=5), t + 432 * S).status, "IDLE")

    def test_never_seen_phone_is_not_lost(self):
        self.assertIsNone(WasherDetector(CFG).tick(10_000 * S))

    def test_disarmed_tick_silent(self):
        d, t = running()
        d.set_armed(False)
        self.assertIsNone(d.tick(t + 10_000 * S))


class Ack(unittest.TestCase):
    def done(self, cfg=CFG):
        d, t = running(cfg)
        d.advance("IDLE", t)
        d.advance("IDLE", t + 120 * S)
        return d, t + 121 * S

    def test_single_shake_not_enough(self):
        d, t = self.done()
        self.assertEqual(d.accept(edge("edge2", 0, t, 5), t).publish, False)
        self.assertEqual(d.state, "DONE")

    def test_shake_streak_broken(self):
        d, t = self.done()
        d.accept(edge("edge2", 0, t, 5), t)
        d.accept(edge("edge2", 1, t, 0), t)
        d.accept(edge("edge2", 2, t, 5), t)
        self.assertEqual(d.state, "DONE")

    def test_two_shakes_clear_alert_and_new_cycle_can_start(self):
        d, t = self.done()
        d.accept(edge("edge2", 0, t, 5), t)
        r = d.accept(edge("edge2", 1, t, 5), t)
        self.assertEqual((r.status, r.clear_alert), ("IDLE", True))
        d.advance("WASHING", t + S)
        self.assertEqual(d.advance("WASHING", t + 62 * S).status, "WASHING")
        self.assertFalse(d.spin_seen)

    def test_shake_outside_done_does_nothing(self):
        d, t = running()
        d.accept(edge("edge2", 0, t, 5), t)
        d.accept(edge("edge2", 1, t, 5), t)
        self.assertEqual(d.state, "SPIN")


class Env(unittest.TestCase):
    def test_real_defaults(self):
        with mock.patch.dict(os.environ, {"CUCI_MODE": "real"}, clear=True):
            c = Config.from_env()
        self.assertEqual((c.min_run_s, c.done_nospin_s, c.ack_windows, c.sensor_lost_s, c.abandon_s), (600, 240, 2, 60, None))

    def test_demo_defaults_keep_short_timing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            c = Config.from_env()
        self.assertEqual((c.start_s, c.done_s, c.min_run_s, c.done_nospin_s, c.sensor_lost_s), (6, 8, 0, 8, 20))

    def test_constructor_defaults_preserve_old_behaviour(self):
        c = Config(1, 2, 3)
        self.assertEqual((c.min_run_s, c.done_nospin_s, c.ack_windows, c.sensor_lost_s), (0, None, 1, None))


if __name__ == "__main__":
    unittest.main()
