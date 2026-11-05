"""Uji dashboard di Chromium nyata lewat broker lokal (TCP + WebSocket).

Payload buatan test dipublikasikan lewat MQTT sungguhan, kecuali test ARM/DISARM yang memakai detector nyata.
Dilewati jika Playwright atau amqtt belum terpasang. Tidak membuktikan koneksi ke HiveMQ atau HP.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import paho.mqtt.client as mqtt

from shared.dashboard_server import start_dashboard_server

ROOT = Path(__file__).resolve().parent.parent
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def telemetry(seq=0, device="edge1", rms=0.5, rot=0.1, boot="b1", v2=True, **over):
    body = {"device_id": device, "boot_id": boot, "sequence": seq, "sent_at_ms": int(time.time() * 1000), "motion_rms": rms, "rotation_rad": rot}
    if v2:
        body.update(schema_version=2, window_s=2.0, n_samples=5, actual_hz=2.0, stale_count=0, acc_dyn_rms=.5, acc_mag_ptp=1.0, gyro_rms=.1, gyro_max=.2, sensor_fault=False, data_source="android")
    body.update(over)
    return body


def status(st="IDLE", reason="Mesin diam", **over):
    body = {"status": st, "reason": reason, "armed": True, "run_minutes": 0.0, "avg_rms": 0.0, "device_id": "edge1", "sequence": 1, "at_ms": int(time.time() * 1000)}
    body.update(over)
    return body


MODEL = dict(detection_mode="HYBRID", effective_mode="HYBRID", model_status="active", model_name="washalert_activity", model_version="v-uji", model_data_kind="real", probability_calibrated=False)


def alert(aid="a1", kind="completed_after_spin", **over):
    now = int(time.time() * 1000)
    body = {"event": "laundry_done", "run_minutes": 42.0, "reason": "Mesin berhenti bergetar: cucian selesai!", "detected_at_ms": now, "alert_id": aid, "kind": kind, "is_reminder": False, "valid_for_s": 660}
    body.update(over)
    return body


@unittest.skipUnless(sync_playwright and shutil.which("amqtt"), "butuh playwright dan amqtt")
class DashboardUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.play = sync_playwright().start()
        cls.browser = cls.play.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.play.stop()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mqtt_port, self.ws_port = free_port(), free_port()
        self.project = "ui_" + os.urandom(3).hex()
        self.prefix = f"washalert/{self.project}/"
        self.config = Path(self.tmp.name) / "broker.yaml"
        self.config.write_text(f"""listeners:
  default:
    type: tcp
    bind: 127.0.0.1:{self.mqtt_port}
  ws:
    type: ws
    bind: 127.0.0.1:{self.ws_port}
plugins:
  amqtt.plugins.authentication.AnonymousAuthPlugin:
    allow_anonymous: true
""")
        self.env = mock.patch.dict(os.environ, {"PROJECT_ID": self.project, "MQTT_HOST": "127.0.0.1", "MQTT_WS_URL": f"ws://127.0.0.1:{self.ws_port}/mqtt", "MQTT_USERNAME": "", "DASHBOARD_STALE_S": "2", "DASHBOARD_OFFLINE_S": "4"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.start_broker()
        self.addCleanup(self.stop_broker)
        self.server, thread, self.url = start_dashboard_server(port=0)
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        self.pub = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id="uji-" + self.project)
        self.pub.reconnect_delay_set(1, 2)
        self.pub.connect_async("127.0.0.1", self.mqtt_port)
        self.pub.loop_start()
        self.addCleanup(self.pub.loop_stop)
        for _ in range(50):
            if self.pub.is_connected():
                break
            time.sleep(.1)
        self.errors = []
        self.page = None

    def tearDown(self):
        if self.page:
            self.page.close()
        self.assertEqual(self.errors, [], "galat JavaScript atau CSP")

    def start_broker(self):
        self.broker = subprocess.Popen(["amqtt", "-c", str(self.config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(75):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", self.mqtt_port)) == 0:
                    return
            time.sleep(.2)
        self.fail("broker tidak hidup")

    def stop_broker(self):
        if self.broker.poll() is None:
            self.broker.kill()
        self.broker.wait()

    def open(self, width=1280, height=900, wait_connect=True, reduced=None):
        context = self.browser.new_context(viewport={"width": width, "height": height}, reduced_motion=reduced)
        self.addCleanup(context.close)
        self.page = context.new_page()
        self.page.on("pageerror", lambda e: self.errors.append(e.message))
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" and "WebSocket" not in m.text else None)
        self.page.goto(self.url + "/")
        if wait_connect:
            self.see("conn", "Tersambung")
        return self.page

    def send(self, topic, body, retain=False):
        payload = body if isinstance(body, (str, bytes)) else json.dumps(body)
        self.pub.publish(self.prefix + topic, payload, qos=1, retain=retain)

    def tele(self, *a, **k):
        body = telemetry(*a, **k)
        self.send(f"edge/{body['device_id']}/telemetry", body)

    def text(self, id_):
        return self.page.text_content("#" + id_) or ""

    def see(self, id_, expected, timeout=8):
        end = time.time() + timeout
        while time.time() < end:
            if expected in self.text(id_):
                return
            self.page.wait_for_timeout(100)
        self.fail(f"#{id_} berisi {self.text(id_)!r}, diharapkan memuat {expected!r}")

    def store(self, expr):
        return self.page.evaluate("() => window.__washalert." + expr)

    # 1, 2
    def test_01_loads_and_02_initial_state_shows_no_fake_values(self):
        self.open()
        self.see("status", "Belum ada", 8)
        self.assertEqual(self.text("minutes"), "Belum ada siklus")
        self.assertEqual(self.text("activity"), "Belum ada data")
        self.assertEqual(self.text("prediction"), "Belum ada prediksi")
        self.assertEqual(self.text("ai-prob"), "Tidak tersedia")
        self.assertEqual(self.text("sensor-badge"), "Menunggu data sensor")
        self.assertEqual(self.text("alert-state"), "Belum ada alert")
        self.assertEqual(self.text("project"), self.project)
        self.assertNotIn("0.000", self.page.inner_text("body"))

    # 3, 5
    def test_03_valid_telemetry_and_05_chart_updates(self):
        self.open()
        blank = self.page.evaluate("document.getElementById('chart-rms').toDataURL()")
        self.tele(0)
        self.tele(1, rms=1.5)
        self.see("sensor-badge", "Live")
        self.see("q-hz", "2.00 Hz")
        self.see("q-source", "Sensor Android")
        self.see("dev-edge1", "HP A: live")
        self.page.wait_for_timeout(600)
        first = self.page.evaluate("document.getElementById('chart-rms').toDataURL()")
        self.assertNotEqual(blank, first)
        self.assertFalse(self.page.is_visible("#empty-rms"))
        self.tele(2, rms=3.0)
        self.page.wait_for_timeout(1300)
        self.assertNotEqual(first, self.page.evaluate("document.getElementById('chart-rms').toDataURL()"))
        self.assertIn("3.000", self.page.get_attribute("#chart-rms", "aria-label"))
        self.assertEqual(self.store("devices.edge1.points.length"), 3)

    def test_chart_breaks_line_across_gap_and_marks_it(self):
        self.open()
        self.tele(0, rms=1.0)
        self.page.wait_for_timeout(5000)   # lebih lama dari batas usang 2 dtk
        self.tele(1, rms=1.0)
        self.page.wait_for_timeout(1300)
        points = self.store("devices.edge1.points.map(p => p.t)")
        self.assertGreater(points[1] - points[0], 2000)
        # pixel di tengah celah: hanya pita celah, tanpa garis data pada ketinggian nilai
        probe = self.page.evaluate("""(pts) => {
          const c = document.getElementById('chart-rms'), g = c.getContext('2d'), r = c.getBoundingClientRect(), dpr = devicePixelRatio;
          const from = Date.now() - 300000, X = (t) => 42 + (t - from) / 300000 * (r.width - 50);
          const x = Math.round((X(pts[0]) + X(pts[1])) / 2 * dpr);
          let band = 0; for (let y = 10; y < c.height - 30; y += 4) { if (g.getImageData(x, y, 1, 1).data[3] > 0) band++; }
          return { band };
        }""", points)
        self.assertGreater(probe["band"], 10, "pita celah harus terlihat")

    # 4
    def test_04_invalid_telemetry_ignored(self):
        self.open()
        self.send("edge/edge1/telemetry", "bukan json")
        self.send("edge/edge1/telemetry", telemetry(0, rms=-1))
        self.send("edge/edge1/telemetry", telemetry(0, device="edge2"))
        self.send("edge/edge9/telemetry", telemetry(0, device="edge9"))
        self.send("edge/edge1/telemetry", {k: v for k, v in telemetry(0).items() if k != "motion_rms"})
        self.send("status", {"status": 5})
        self.see("q-rej-br", "6 rusak")
        self.assertEqual(self.store("devices.edge1.points.length"), 0)
        self.assertEqual(self.text("sensor-badge"), "Menunggu data sensor")

    # 6, FR-075
    def test_06_ml_prediction_rendered_without_confidence_label(self):
        self.open()
        self.send("status", status("SPIN", "Getaran keras", activity="SPIN", activity_source="model", classified_at_ms=int(time.time() * 1000), model_probability=.871, inference_latency_ms=.8, **MODEL))
        self.see("prediction", "SPIN")
        self.see("prediction-sub", "87%, belum terkalibrasi")
        self.see("ai-prob", "87.1%")
        self.see("ai-latency", "0.80 ms")
        self.see("ai-name", "washalert_activity")
        self.see("ai-version", "v-uji")
        self.see("model-badge", "Model dimuat")
        self.see("ai-source", "Model")
        self.assertNotRegex(self.page.inner_text("body").lower(), r"confidence|keyakinan|akurasi \d")

    # 7
    def test_07_unknown_model_status(self):
        self.open()
        self.send("status", status())   # detector lama tanpa field model
        self.see("model-badge", "Status model tidak diketahui")
        self.see("prediction-sub", "tidak dilaporkan")

    # 8
    def test_08_rule_only(self):
        self.open()
        self.send("status", status(detection_mode="RULE_ONLY", effective_mode="RULE_ONLY", model_status="not_configured", activity="IDLE", activity_source="rule"))
        self.see("prediction", "AI tidak aktif")
        self.see("effective-mode", "RULE_ONLY")
        self.see("mode-chip", "RULE_ONLY")
        self.see("ai-source", "bukan AI")
        self.see("model-badge", "Model tidak dipakai")

    # 9
    def test_09_hybrid_fallback_is_visible(self):
        self.open()
        self.send("status", status(detection_mode="HYBRID", effective_mode="RULE_ONLY", model_status="unavailable", fallback_reason="model_hash_mismatch", activity="IDLE", activity_source="rule"))
        self.see("mode-chip", "RULE_ONLY, diminta HYBRID")
        self.see("prediction", "Model tidak dimuat")
        self.see("ai-fallback", "file model berubah atau rusak")
        self.see("banners", "Model tidak dipakai")
        self.see("events", "Model tidak dipakai")

    def test_09b_hybrid_window_fallback(self):
        self.open()
        self.send("status", status("WASHING", "Mesin mencuci", activity="WASHING", activity_source="rule_fallback", activity_reason="incomplete_window", **MODEL))
        self.see("prediction", "Tidak dipakai saat ini")
        self.see("ai-fallback", "jendela 30 detik belum lengkap")

    # 10
    def test_10_synthetic_and_simulation_markers(self):
        self.open()
        self.send("status", status(activity="IDLE", activity_source="model", **{**MODEL, "model_data_kind": "synthetic"}))
        self.see("banners", "MODEL PENGEMBANGAN (SINTETIS)")
        self.see("ai-kind", "SINTETIS")
        self.see("model-badge", "sintetis")
        self.tele(0, data_source="simulator")
        self.see("banners", "MODE SIMULASI")
        self.see("q-source", "SIMULATOR")

    def test_real_android_data_has_no_simulation_marker(self):
        self.open()
        self.tele(0)
        self.see("sensor-badge", "Live")
        self.assertNotIn("SIMULASI", self.text("banners"))

    # 11, 12, skenario G
    def test_11_mqtt_disconnected_and_12_reconnected(self):
        self.open()
        self.send("status", status("WASHING", "Mesin mencuci", run_minutes=3.0))
        self.tele(0)
        self.see("status", "WASHING")
        self.stop_broker()
        self.see("conn", "Terputus", 15)
        self.see("door-note", "Broker terputus")
        self.assertEqual(self.page.get_attribute("#door", "data-fresh"), "stale")
        self.see("dev-detector", "broker putus")
        self.see("dev-edge1", "broker putus")
        self.see("sensor-badge", "Broker terputus")
        self.start_broker()
        self.see("conn", "Tersambung", 25)
        for _ in range(50):
            if self.pub.is_connected():
                break
            time.sleep(.2)
        self.send("status", status("WASHING", "Mesin mencuci", run_minutes=3.2))
        self.tele(1)
        self.see("sensor-badge", "Live")
        self.see("events", "Tersambung ke broker")
        self.assertEqual(self.page.get_attribute("#door", "data-fresh"), "live")

    # 13
    def test_13_stale_then_offline_sensor(self):
        self.open()
        self.send("status", status("WASHING", "Mesin mencuci"))
        self.tele(0)
        self.see("sensor-badge", "Live")
        self.see("sensor-badge", "Data usang", 5)
        self.see("dev-edge1", "data usang")
        self.assertEqual(self.page.get_attribute("#door", "data-fresh"), "stale")
        self.see("sensor-badge", "HP A offline", 5)
        self.see("dev-edge1", "offline")

    def test_detector_offline_from_last_will(self):
        self.open()
        self.send("status", status("OFFLINE", "Detector terputus", armed=False, device_id=None))
        self.see("status", "OFFLINE")
        self.see("dev-detector", "offline")
        self.assertEqual(self.page.get_attribute("#door", "data-fresh"), "offline")
        self.see("armed", "detector offline")

    def test_sensor_v1_and_fault_differ(self):
        self.open()
        self.tele(0, v2=False)
        self.see("q-hz", "telemetri v1")
        self.see("q-badge", "Telemetri v1")
        self.tele(1, sensor_fault=True)
        self.see("q-fault", "Gagal terbaca")
        self.see("q-badge", "Sensor gagal")

    # 14, 15
    def test_14_alert_received_and_15_acknowledged(self):
        self.open()
        self.send("status", status("DONE", "Cucian selesai", run_minutes=42.0, spin_seen=True, **MODEL))
        self.send("alerts", alert())
        self.send("alert_state", {**alert(), "active": True, "updated_at_ms": int(time.time() * 1000)})
        self.see("alert-state", "Cucian selesai, menunggu konfirmasi")
        self.see("alert-active", "menggoyang HP B")
        self.see("alert-active", "Spin terdeteksi")
        self.see("alerts", "Menunggu konfirmasi")
        self.send("alerts", alert("a2", is_reminder=True, reason="Pengingat: cucian belum diambil"))
        self.see("alerts", "1 pengingat")
        self.send("alert_state", {"active": False, "alert_id": "a2", "ended_by": "acknowledged", "updated_at_ms": int(time.time() * 1000)})
        self.see("alerts", "Dikonfirmasi pemilik")
        self.see("events", "mengonfirmasi lewat HP B")
        self.assertFalse(self.page.is_visible("#alert-active"))
        self.assertEqual(self.page.locator("button", has_text="Konfirmasi").count(), 0)

    def test_alert_retained_state_and_expiry(self):
        self.send("alert_state", {**alert(detected_at_ms=int(time.time() * 1000) - 2000, valid_for_s=4), "active": True}, retain=True)
        self.page = None
        self.open()
        self.see("alerts", "Menunggu konfirmasi")
        self.see("alerts", "Kedaluwarsa", 6)

    def test_alert_superseded_and_info_kinds(self):
        self.open()
        self.send("alerts", alert())
        self.see("alerts", "Menunggu konfirmasi")
        self.send("alert_state", {"active": False, "ended_by": "superseded"})
        self.see("alerts", "Digantikan koreksi")
        self.send("alerts", alert("a9", kind="sensor_lost", event="sensor_lost", reason="HP A hilang"))
        self.see("alerts", "HP A tidak mengirim data")
        self.see("alerts", "Informasi")

    # 16, 17, skenario I, dengan detector nyata
    def detector(self):
        log = open(Path(self.tmp.name) / "d.log", "w")
        env = dict(os.environ, MQTT_PORT=str(self.mqtt_port), MQTT_TLS="false", ALLOW_INSECURE_LOCAL="true", DASHBOARD_PORT=str(free_port()), PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1", DETECTION_MODE="RULE_ONLY", CUCI_MODE="demo")
        p = subprocess.Popen([sys.executable, "detector.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        self.addCleanup(lambda: (p.kill(), p.wait(), log.close()))
        return p

    def test_16_arm_and_17_disarm_confirmed_by_detector(self):
        self.detector()
        self.open()
        self.see("status", "ONLINE", 20)
        self.see("armed", "Aktif")
        self.page.click("#btn-disarm")
        self.assertTrue(self.page.is_visible("#btn-disarm-yes"))
        self.assertEqual(self.text("status"), "ONLINE")   # belum ada perintah
        self.page.click("#btn-disarm-no")
        self.assertEqual(self.text("armed"), "Aktif (ARM)")
        self.page.click("#btn-disarm")
        self.page.click("#btn-disarm-yes")
        self.see("cmd-feedback", "Detector mengonfirmasi DISARM")
        self.see("status", "DISARMED")
        self.see("armed", "Dijeda")
        self.page.click("#btn-arm")
        self.see("cmd-feedback", "Detector mengonfirmasi ARM")
        self.see("status", "IDLE")
        self.see("armed", "Aktif")

    # 18
    def test_18_command_timeout_does_not_change_status(self):
        self.open()
        self.send("status", status())
        self.see("status", "IDLE")
        self.page.click("#btn-arm")
        self.assertTrue(self.page.is_disabled("#btn-arm"))
        self.see("cmd-feedback", "Batas waktu ARM", 10)
        self.assertEqual(self.text("status"), "IDLE")
        self.assertFalse(self.page.is_disabled("#btn-arm"))

    def test_18b_command_fails_when_disconnected(self):
        self.open()
        self.stop_broker()
        self.see("conn", "Terputus", 15)
        self.page.click("#btn-arm")
        self.see("cmd-feedback", "ARM gagal")

    # 19
    def test_19_duplicates_do_not_create_events(self):
        self.open()
        same = telemetry(5)
        for _ in range(3):
            self.send("edge/edge1/telemetry", same)
        older = telemetry(4)
        self.send("edge/edge1/telemetry", older)
        one = status("DONE", "Selesai")
        for _ in range(3):
            self.send("status", one)
        for _ in range(3):
            self.send("alerts", alert("dup"))
        self.see("q-rej-br", "5 duplikat")
        self.assertEqual(self.store("devices.edge1.points.length"), 1)
        self.assertEqual(self.store("alerts.length"), 1)
        self.assertEqual(self.store("events.filter(e => e.kind === 'cycle').length"), 1)
        self.see("dup-note", "2 alert duplikat")

    def test_new_boot_id_resets_sequence(self):
        self.open()
        self.tele(9, boot="b1")
        self.tele(0, boot="b2")
        self.page.wait_for_timeout(500)
        self.assertEqual(self.store("devices.edge1.points.length"), 2)

    # 20, skenario J
    def test_20_responsive_no_horizontal_scroll(self):
        for width, height in ((360, 740), (768, 1024), (1280, 800)):
            with self.subTest(width=width):
                self.open(width, height)
                self.send("status", status("SPIN", "Getaran keras: fase peras (spin) dengan alasan yang cukup panjang untuk diuji", activity="SPIN", activity_source="model", model_probability=.9, **{**MODEL, "model_version": "syn_hard_v1-v1-decision_tree-F2-624d6645", "model_data_kind": "synthetic"}))
                self.send("alerts", alert(f"r{width}"))
                self.tele(width, )
                self.see("status", "SPIN")
                self.page.wait_for_timeout(1200)
                sizes = self.page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
                self.assertLessEqual(sizes[0], sizes[1], f"overflow {sizes}")
                for sel in ("#btn-arm", "#btn-disarm", "#range"):
                    box = self.page.locator(sel).bounding_box()
                    self.assertGreaterEqual(box["height"], 44, sel)
                self.assertLessEqual(self.page.locator("#chart-rms").bounding_box()["width"], width)
                self.page.close()
                self.page = None

    # keamanan
    def test_markup_in_payload_is_shown_as_text(self):
        self.open()
        evil = "<img src=x onerror=window.__xss=1>"
        self.send("status", status(evil[:60], evil, activity=evil, activity_source=evil, model_status="active", model_name=evil, model_version=evil))
        self.send("alerts", alert("x", kind=evil, reason=evil))
        self.see("reason", "<img")
        self.see("status", "UNKNOWN")
        self.see("alerts", "<img")
        self.page.wait_for_timeout(1200)
        self.assertEqual(self.page.locator("main img, #banners img").count(), 0)
        self.assertIsNone(self.page.evaluate("window.__xss ?? null"))

    def test_no_secret_or_inline_handlers_or_fixed_metrics_in_source(self):
        files = [ROOT / "dashboard/index.html", *(ROOT / "dashboard/assets/js").glob("*.js")]
        source = "\n".join(p.read_text(encoding="utf-8") for p in files)
        self.assertNotRegex(source, r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\seval\(|onclick=")
        self.assertNotRegex(source, r"(?i)accuracy|f1[-_ ]?score|\b9\d(\.\d+)?\s*%")
        self.assertNotRegex(source, r"(?i)password\s*[:=]\s*[\"'][^\"']+")
        self.assertIn("Content-Security-Policy", (ROOT / "dashboard/index.html").read_text())

    def test_credentials_form_stays_in_memory(self):
        os.environ["MQTT_USERNAME"] = "akun"
        fake = """window.mqtt = { connect: (url, o) => { window.__opts = o; return { on: () => {}, end: () => {} }; } };"""
        context = self.browser.new_context()
        self.addCleanup(context.close)
        self.page = context.new_page()
        self.page.route("**/mqtt.min.js", lambda r: r.fulfill(body=fake, content_type="application/javascript"))
        self.page.goto(self.url + "/")
        self.see("conn", "Perlu login")
        self.assertIsNone(self.page.evaluate("window.__opts ?? null"))
        self.page.fill("#login-user", "akun")
        self.page.fill("#login-pass", "rahasia")
        self.page.click("#login button")
        self.assertEqual(self.page.evaluate("window.__opts.username"), "akun")
        self.assertEqual(self.page.input_value("#login-pass"), "")
        self.assertEqual(self.page.evaluate("JSON.stringify(localStorage)").count("rahasia"), 0)
        self.assertEqual(self.page.evaluate("JSON.stringify(sessionStorage)").count("rahasia"), 0)

    def test_missing_library_and_config_errors_are_stated(self):
        context = self.browser.new_context()
        self.addCleanup(context.close)
        self.page = context.new_page()
        self.page.route("**/config.json", lambda r: r.fulfill(status=500, body="x"))
        self.page.goto(self.url + "/")
        self.see("conn", "Galat")
        self.see("door-note", "config.json")
        self.errors.clear()

    # aksesibilitas
    def test_keyboard_focus_reaches_controls_and_reduced_motion(self):
        self.open(reduced="reduce")
        self.send("status", status("SPIN", "Getaran keras"))
        self.tele(0)
        self.see("status", "SPIN")
        self.see("sensor-badge", "Live")
        self.assertEqual(self.page.evaluate("getComputedStyle(document.querySelector('.drum')).animationName"), "none")
        seen = []
        for _ in range(12):
            self.page.keyboard.press("Tab")
            seen.append(self.page.evaluate("document.activeElement.id"))
        for wanted in ("btn-arm", "btn-disarm", "range", "chart-rms"):
            self.assertIn(wanted, seen)
        self.assertEqual(self.page.evaluate("document.querySelectorAll('h1').length"), 1)
        self.assertEqual(self.page.get_attribute("#status", "role"), "status")

    def test_spin_animates_when_motion_allowed(self):
        self.open(reduced="no-preference")
        self.send("status", status("SPIN", "Getaran keras"))
        self.tele(0)
        self.see("status", "SPIN")
        self.see("sensor-badge", "Live")
        self.page.wait_for_timeout(400)
        self.assertEqual(self.page.evaluate("getComputedStyle(document.querySelector('.drum')).animationName"), "turn")

    # linimasa
    def test_timeline_shows_recorded_path_only_and_idle_is_not_done(self):
        self.open()
        t = int(time.time() * 1000) - 60000
        for i, (st, act, src) in enumerate((("IDLE", "IDLE", "rule"), ("WASHING", "WASHING", "model"), ("WASHING", "IDLE", "model"), ("DONE", "IDLE", "model"))):
            self.send("status", status(st, "r", at_ms=t + i * 15000, activity=act, activity_source=src))
            self.page.wait_for_timeout(80)
        self.see("path", "IDLE → WASHING → DONE")
        self.assertNotIn("SPIN", self.text("path"))
        self.page.wait_for_timeout(1200)
        lanes = self.page.evaluate("[...document.querySelectorAll('.track')].map(t => [...t.querySelectorAll('.seg')].map(s => s.dataset.v))")
        self.assertEqual(lanes[0], ["IDLE", "WASHING", "DONE"])
        self.assertEqual(lanes[1], ["IDLE", "WASHING", "IDLE"])   # aktivitas IDLE sementara status masih WASHING

    def test_history_is_bounded(self):
        self.open()
        self.page.evaluate("""() => { const s = window.__washalert;
          for (let i = 0; i < 5000; i++) { s.onTelemetry('edge1', {device_id:'edge1',boot_id:'b',sequence:i,sent_at_ms:1,motion_rms:.1,rotation_rad:0}, Date.now()); s.addEvent(1,'x','x'); } }""")
        self.assertEqual(self.store("devices.edge1.points.length"), 1200)
        self.assertEqual(self.store("events.length"), 100)


if __name__ == "__main__":
    unittest.main()
