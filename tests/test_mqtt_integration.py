"""Integrasi nyata lewat broker lokal amqtt, tanpa TLS dan tanpa HP.

Dilewati jika amqtt belum terpasang (requirements-dev.txt). Tidak membuktikan koneksi ke HiveMQ.
"""
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

import paho.mqtt.client as mqtt

from ml.build_dataset import edge_windows
from ml.validate_dataset import validate_session
from shared import edge_runner
from shared.features import telemetry_extra
from shared.messages import Telemetry

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "uji_integrasi"
PREFIX = f"washalert/{PROJECT}/"
_found = glob.glob("models/development/SYNTHETIC_*", root_dir=ROOT)
SYN_MODEL = str(ROOT / _found[0]) if _found else None


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Publish(unittest.TestCase):
    def test_not_connected_drops_without_exception(self):
        client = mock.Mock()
        client.is_connected.return_value = False
        self.assertFalse(edge_runner.publish_when_connected(client, "t", "{}"))
        client.publish.assert_not_called()

    def test_publish_error_does_not_raise(self):
        client = mock.Mock()
        client.is_connected.return_value = True
        client.publish.return_value.wait_for_publish.side_effect = RuntimeError("putus")
        with mock.patch("builtins.print"):
            self.assertFalse(edge_runner.publish_when_connected(client, "t", "{}"))


@unittest.skipUnless(shutil.which("amqtt"), "amqtt belum terpasang")
class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.port = free_port()
        self.config = Path(self.tmp.name) / "broker.yaml"
        self.config.write_text(f"""listeners:
  default:
    type: tcp
    bind: 127.0.0.1:{self.port}
plugins:
  amqtt.plugins.authentication.AnonymousAuthPlugin:
    allow_anonymous: true
""")
        self.procs = []
        self.broker = None
        self.messages = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
            if p.stdout:
                p.stdout.close()
        self.stop_broker()
        if getattr(self, "listener", None):
            self.listener.loop_stop()

    def start_broker(self):
        self.broker = subprocess.Popen(["amqtt", "-c", str(self.config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 15
        while time.time() < deadline:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", self.port)) == 0:
                    return
            time.sleep(0.2)
        self.fail("Broker tidak hidup")

    def stop_broker(self):
        if self.broker and self.broker.poll() is None:
            self.broker.kill()
            self.broker.wait()
        self.broker = None

    def env(self):
        env = dict(os.environ, PROJECT_ID=PROJECT, MQTT_HOST="127.0.0.1", MQTT_PORT=str(self.port), MQTT_TLS="false",
                   ALLOW_INSECURE_LOCAL="true", CUCI_MODE="demo", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1",
                   DASHBOARD_PORT=str(free_port()), MQTT_WS_URL="")
        env.update(getattr(self, "extra_env", {}))
        return env

    def spawn(self, *cmd):
        log = open(Path(self.tmp.name) / f"p{len(self.procs)}.log", "w+")
        p = subprocess.Popen([sys.executable, *cmd], cwd=ROOT, env=self.env(), stdout=log, stderr=subprocess.STDOUT)
        p.log_path = log.name
        p.stdout = log
        self.procs.append(p)
        return p

    def listen(self, *topics):
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id=f"uji-{time.time()}")
        client.reconnect_delay_set(1, 2)
        client.on_connect = lambda c, u, f, r, p: [c.subscribe(PREFIX + t, qos=1) for t in topics]
        client.on_message = lambda c, u, m: self.messages.append((time.time(), m.topic, m.payload))
        client.connect_async("127.0.0.1", self.port, keepalive=30)
        client.loop_start()
        self.listener = client

    def wait_until(self, check, timeout, what):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if check():
                return
            time.sleep(0.2)
        self.fail(f"Tidak terjadi dalam {timeout} dtk: {what}")

    # ---------- Phase 6: detector utuh lewat broker ----------
    def send(self, device, seq, rms, rot=0.0, extra=None):
        body = Telemetry.make(device, "uji", seq, rms, rot, extra).to_json()
        self.listener.publish(f"{PREFIX}edge/{device}/telemetry", body, qos=1)

    def bodies(self, name):
        return [json.loads(m[2]) for m in list(self.messages) if m[1].endswith("/" + name)]

    def run_active(self):
        """Kirim getaran sampai siklus mulai. Pesan awal bisa hilang jika subscribe detector belum selesai."""
        seq = 0
        deadline = time.time() + 20
        while not any(b["status"] in ("WASHING", "SPIN") for b in self.bodies("status")):
            self.assertLess(time.time(), deadline, "siklus tidak mulai")
            self.send("edge1", seq, 3.0, 0.6)
            seq += 1
            time.sleep(0.5)
        return seq

    def cycle(self):
        """Getar, diam, alert, goyang, IDLE. Berlaku untuk semua mode."""
        seq = self.run_active()
        for _ in range(20):
            self.send("edge1", seq, 0.0)
            seq += 1
            time.sleep(0.5)
            if self.bodies("alerts"):
                break
        self.wait_until(lambda: self.bodies("alerts"), 5, "alert")
        self.wait_until(lambda: any(b.get("active") for b in self.bodies("alert_state")), 5, "alert_state aktif")
        self.send("edge2", 0, 6.0)
        time.sleep(0.5)  # broker lokal tidak menjamin urutan dua pesan yang dikirim bersamaan
        self.send("edge2", 1, 6.0)
        self.wait_until(lambda: self.bodies("status")[-1]["status"] == "IDLE" and "konfirmasi" in self.bodies("status")[-1]["reason"], 8, "konfirmasi")
        self.wait_until(lambda: self.bodies("alert_state")[-1]["active"] is False, 5, "alert_state bersih")

    def start_detector(self, **env):
        self.extra_env = {"CUCI_START_S": "1", "CUCI_DONE_S": "2", "CUCI_DONE_NOSPIN_S": "2", "CUCI_REMIND_S": "60", **env}
        self.start_broker()
        self.listen("status", "alerts", "alert_state")
        self.wait_until(lambda: self.listener.is_connected(), 10, "listener")
        time.sleep(0.5)
        detector = self.spawn("detector.py")
        self.wait_until(lambda: self.bodies("status"), 20, "status pertama")
        return detector

    def test_rule_only_full_cycle(self):
        self.start_detector()
        self.assertEqual(self.bodies("status")[0]["effective_mode"], "RULE_ONLY")
        self.cycle()
        self.assertEqual(self.bodies("status")[-1]["activity_source"] if "activity_source" in self.bodies("status")[-1] else "rule", "rule")

    def test_hybrid_missing_model_falls_back_and_cycle_still_works(self):
        self.start_detector(DETECTION_MODE="HYBRID", MODEL_PATH="/tidak/ada")
        first = self.bodies("status")[0]
        self.assertEqual((first["detection_mode"], first["effective_mode"], first["fallback_reason"]), ("HYBRID", "RULE_ONLY", "model_missing"))
        self.cycle()

    @unittest.skipUnless(SYN_MODEL, "model sintetis belum dibangun")
    def test_hybrid_blocks_synthetic_model_by_default(self):
        self.start_detector(DETECTION_MODE="HYBRID", MODEL_PATH=SYN_MODEL)
        self.assertEqual(self.bodies("status")[0]["fallback_reason"], "synthetic_not_allowed")

    def test_unknown_mode_refused_at_start(self):
        self.extra_env = {"DETECTION_MODE": "AI"}
        detector = self.spawn("detector.py")
        self.assertEqual(detector.wait(timeout=20), 1)
        self.assertIn("DETECTION_MODE tidak dikenal", Path(detector.log_path).read_text())

    def test_ml_only_without_model_reports_rule_only_and_cycle_works(self):
        self.start_detector(DETECTION_MODE="ML_ONLY")
        first = self.bodies("status")[0]
        self.assertEqual((first["detection_mode"], first["effective_mode"], first["fallback_reason"]), ("ML_ONLY", "RULE_ONLY", "model_missing"))
        self.cycle()

    @unittest.skipUnless(SYN_MODEL, "model sintetis belum dibangun")
    def test_corrupted_model_falls_back(self):
        bad = Path(self.tmp.name) / "model"
        shutil.copytree(SYN_MODEL, bad)
        with open(bad / "model.joblib", "ab") as f:
            f.write(b"rusak")
        self.start_detector(DETECTION_MODE="HYBRID", MODEL_PATH=str(bad), ALLOW_SYNTHETIC_MODEL="true")
        self.assertEqual(self.bodies("status")[0]["fallback_reason"], "model_hash_mismatch")
        self.cycle()

    def test_detector_restart_restores_done(self):
        path = str(Path(self.tmp.name) / "state.json")
        detector = self.start_detector(DETECTOR_STATE_PATH=path)
        seq = self.run_active()
        while not self.bodies("alerts"):
            self.send("edge1", seq, 0.0)
            seq += 1
            time.sleep(0.5)
        time.sleep(0.5)
        detector.terminate()
        detector.wait(timeout=10)
        count = len(self.messages)
        self.spawn("detector.py")
        self.wait_until(lambda: any(json.loads(m[2]).get("status") == "DONE" for m in self.messages[count:] if m[1].endswith("/status")), 25, "DONE pulih")

    def test_sensor_lost_published_by_tick(self):
        self.start_detector(CUCI_SENSOR_LOST_S="3")
        self.run_active()
        self.wait_until(lambda: any(b["status"] == "SENSOR_LOST" for b in self.bodies("status")), 12, "SENSOR_LOST")
        self.assertEqual(self.bodies("alerts")[-1]["kind"], "sensor_lost")

    def test_cycle_state_survives_broker_restart(self):
        self.start_detector(CUCI_SENSOR_LOST_S="0")
        self.run_active()
        self.wait_until(lambda: self.bodies("status")[-1]["status"] in ("WASHING", "SPIN"), 8, "mulai")
        self.stop_broker()
        time.sleep(2)
        count = len(self.messages)
        self.start_broker()
        self.wait_until(lambda: any(b["status"] in ("WASHING", "SPIN") for b in [json.loads(m[2]) for m in self.messages[count:] if m[1].endswith("/status")]), 30, "state setelah pulih")

    def test_alert_state_retained_for_late_subscriber(self):
        self.start_detector()
        seq = self.run_active()
        while not self.bodies("alerts"):
            self.send("edge1", seq, 0.0)
            seq += 1
            time.sleep(0.5)
        got = []
        late = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id="uji-telat")
        late.on_connect = lambda c, u, f, r, p: c.subscribe(PREFIX + "alert_state", qos=1)
        late.on_message = lambda c, u, m: got.append(json.loads(m.payload))
        late.connect("127.0.0.1", self.port)
        late.loop_start()
        self.addCleanup(late.loop_stop)
        self.wait_until(lambda: got, 8, "alert_state retained")
        self.assertTrue(got[-1]["active"])

    @unittest.skipUnless(SYN_MODEL and os.getenv("WASHALERT_SLOW"), "lambat: butuh jendela agregat nyata dan model sintetis; set WASHALERT_SLOW=1")
    def test_hybrid_synthetic_model_runs_end_to_end(self):
        """Uji perangkat lunak dengan model SINTETIS. Bukan bukti performa pada mesin cuci."""
        self.start_detector(DETECTION_MODE="HYBRID", MODEL_PATH=SYN_MODEL, ALLOW_SYNTHETIC_MODEL="true")
        first = self.bodies("status")[0]
        self.assertEqual((first["effective_mode"], first["model_data_kind"]), ("HYBRID", "synthetic"))
        report = validate_session(ROOT / "data/synthetic/SYNTHETIC_SYNM1_C04")
        labels = sorted(report.labels, key=lambda l: l["start_ms"])
        span = next(l for l in labels if l["label"] == "WASHING")
        windows = [w for _, end, w in edge_windows(report.rows, int(report.meta["samples_per_window"]), report.median_dt, Counter())
                   if span["start_ms"] <= end <= span["end_ms"]]
        for seq, w in enumerate(windows[:30]):
            self.send("edge1", seq, w["motion_rms"], w["rotation_rad"], telemetry_extra(w))
            time.sleep(1)
        statuses = self.bodies("status")
        sources = {b.get("activity_source") for b in statuses}
        self.assertIn("rule_fallback", sources)   # jendela agregat belum lengkap di awal
        self.assertIn("model", sources)
        used = next(b for b in statuses if b.get("activity_source") == "model")
        self.assertIn("model_probability", used)
        self.assertEqual(used["model_data_kind"], "synthetic")

    def test_edge_starts_before_broker_and_telemetry_is_v2(self):
        edge = self.spawn("hp_mesin.py", "--source", "simulator", "--interval", "0.05")
        time.sleep(3)
        self.assertIsNone(edge.poll(), "Edge mati karena broker belum ada")
        self.start_broker()
        self.listen("edge/+/telemetry")
        self.wait_until(lambda: self.messages, 25, "telemetri pertama")
        body = json.loads(self.messages[-1][2])
        self.assertEqual(body["schema_version"], 2)
        self.assertIn("motion_rms", body)
        self.assertGreater(body["window_s"], 0)
        self.assertEqual(body["n_samples"], 5)
        self.assertIs(body["sensor_fault"], False)

    def test_edge_survives_three_broker_restarts(self):
        """NFR pemulihan: telemetri kembali dalam 30 dtk pada 3 dari 3 restart."""
        self.start_broker()
        self.listen("edge/+/telemetry")
        edge = self.spawn("hp_mesin.py", "--source", "simulator", "--interval", "0.05")
        self.wait_until(lambda: self.messages, 25, "telemetri pertama")
        recoveries = []
        for _ in range(3):
            self.stop_broker()
            time.sleep(4)
            self.assertIsNone(edge.poll(), "Edge mati saat broker putus")
            self.start_broker()
            restarted = time.time()
            count = len(self.messages)
            self.wait_until(lambda: len(self.messages) > count, 30, "telemetri setelah pulih")
            recoveries.append(round(self.messages[count][0] - restarted, 1))
        print(f"\n[MQTT] waktu pulih setelah broker hidup (dtk): {recoveries}")
        self.assertIsNone(edge.poll())

    def test_detector_starts_before_broker(self):
        detector = self.spawn("detector.py")
        time.sleep(3)
        self.assertIsNone(detector.poll(), "Detector mati karena broker belum ada")
        self.start_broker()
        self.listen("status")
        self.wait_until(lambda: self.messages, 25, "status detector")

    def test_detector_resubscribes_after_broker_restart(self):
        self.start_broker()
        detector = self.spawn("detector.py")
        self.wait_until(lambda: "Subscribe" in Path(detector.log_path).read_text(), 20, "subscribe pertama")
        self.stop_broker()
        time.sleep(3)
        self.assertIsNone(detector.poll())
        self.start_broker()
        self.wait_until(lambda: Path(detector.log_path).read_text().count("Subscribe") >= 2, 30, "subscribe ulang")

    @unittest.skipUnless(os.getenv("WASHALERT_SLOW"), "Skenario 50 dtk. Set WASHALERT_SLOW=1")
    def test_full_cycle_alert_and_ack_unchanged(self):
        self.start_broker()
        self.listen("status", "alerts")
        self.spawn("detector.py")
        time.sleep(2)
        self.spawn("hp_mesin.py", "--source", "simulator")
        owner = self.spawn("hp_pemilik.py", "--source", "simulator")
        self.wait_until(lambda: any(t.endswith("alerts") for _, t, _ in self.messages), 60, "alert")
        def acked():
            return any(t.endswith("status") and b"konfirmasi cucian" in p for _, t, p in self.messages)
        self.wait_until(acked, 30, "konfirmasi")
        alert = json.loads(next(p for _, t, p in self.messages if t.endswith("alerts")))
        self.assertEqual(alert["event"], "laundry_done")
        self.assertIn("ALARM", Path(owner.log_path).read_text())


if __name__ == "__main__":
    unittest.main()
