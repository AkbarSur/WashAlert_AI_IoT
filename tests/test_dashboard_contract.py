"""Kontrak data yang dibutuhkan dashboard dari detector, tanpa browser dan broker."""
import json
import os
import unittest
from unittest import mock

from nodes.detector_service.main import DetectorService
from nodes.detector_service.rules import Config, Decision, WasherDetector
from shared.dashboard_server import public_browser_config, start_dashboard_server

NOW = 2_000_000_000_000


class Contract(unittest.TestCase):
    def setUp(self):
        self.client = mock.Mock()
        self.s = DetectorService(self.client, WasherDetector(Config(0, 1, 300)), {"detection_mode": "RULE_ONLY", "effective_mode": "RULE_ONLY", "model_status": "not_configured"},
                                 clock=lambda: NOW / 1000, log=lambda *a: None)

    def sent(self, name):
        return [json.loads(c.args[1]) for c in self.client.publish.call_args_list if c.args[0].endswith("/" + name)]

    def activate(self):
        self.s.apply(Decision("DONE", "x", alert=True, alert_kind="completed_after_spin"))

    def test_command_reply_carries_last_command(self):
        for command in ("ARM", "DISARM"):
            self.s.handle_control(command.encode())
            self.assertEqual(self.sent("status")[-1]["last_command"], command)

    def test_ordinary_status_has_no_last_command(self):
        self.s.publish_status("IDLE", "x")
        self.assertNotIn("last_command", self.sent("status")[-1])

    def test_invalid_command_gets_no_confirmation(self):
        self.s.handle_control(b"RESET")
        self.assertEqual(self.sent("status"), [])

    def test_alert_end_reason_acknowledged(self):
        self.activate()
        self.s.apply(Decision("IDLE", "konfirmasi", clear_alert=True))
        self.assertEqual(self.sent("alert_state")[-1]["ended_by"], "acknowledged")

    def test_alert_end_reason_superseded(self):
        self.activate()
        self.s.apply(Decision("WASHING", "k", alert=True, alert_kind="correction", clear_alert=True))
        self.assertEqual(self.sent("alert_state")[-1]["ended_by"], "superseded")

    def test_alert_end_reason_disarmed(self):
        self.activate()
        self.s.handle_control(b"DISARM")
        self.assertEqual(self.sent("alert_state")[-1]["ended_by"], "disarmed")


class ServerConfig(unittest.TestCase):
    def test_thresholds_public_and_bad_values_use_default(self):
        with mock.patch.dict(os.environ, {"DASHBOARD_STALE_S": "7", "DASHBOARD_OFFLINE_S": "abc"}):
            c = public_browser_config()
        self.assertEqual((c["stale_after_s"], c["offline_after_s"]), (7, 60))

    def test_binds_localhost_by_default(self):
        with mock.patch.dict(os.environ, {"DASHBOARD_HOST": "127.0.0.1"}):
            server, thread, url = start_dashboard_server(port=0)
        self.assertEqual(server.server_address[0], "127.0.0.1")
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    def test_edge_labels_data_source(self):
        with open("shared/edge_runner.py", encoding="utf-8") as f:
            self.assertIn('"data_source": args.source', f.read())


if __name__ == "__main__":
    unittest.main()
