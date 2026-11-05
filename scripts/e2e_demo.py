"""Demo end-to-end skenario A sampai J. SIMULATION: broker lokal, telemetri sintetis, tanpa HP dan mesin cuci.

Komponen nyata yang berjalan: detector.py, hp_pemilik.py (--source simulator), dashboard, model sintetis Phase 5.
Hasil ini menguji perangkat lunak. Ini bukan hardware validation dan bukan bukti akurasi pada mesin cuci.

    python -m scripts.e2e_demo --model models/development/SYNTHETIC_... --out reports/e2e
    # opsional, periksa juga dashboard di Chromium dan simpan screenshot: --browser

Butuh amqtt (requirements-dev.txt). Lama berjalan sekitar 8 menit.
"""

import argparse
import json
import os
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import Counter
from pathlib import Path

import paho.mqtt.client as mqtt

from ml.build_dataset import edge_windows
from ml.validate_dataset import validate_session
from shared.features import telemetry_extra
from shared.messages import Telemetry

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "demo_e2e"
PREFIX = f"washalert/{PROJECT}/"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def load_windows(session: Path) -> dict:
    """Jendela per label dari rekaman SINTETIS yang tidak dipakai melatih model (grup test)."""
    report = validate_session(session)
    out = {"IDLE": [], "WASHING": [], "SPIN": []}
    labels = report.labels
    for _, end, w in edge_windows(report.rows, int(report.meta["samples_per_window"]), report.median_dt, Counter()):
        for l in labels:
            if l["start_ms"] <= end <= l["end_ms"] and l["label"] in out:
                out[l["label"]].append(w)
    return out


class Demo:
    def __init__(self, args):
        self.args = args
        self.tmp = Path(tempfile.mkdtemp(prefix="washalert_e2e_"))
        self.mqtt_port, self.ws_port, self.dash_port = free_port(), free_port(), free_port()
        self.msgs, self.sent_at, self.results, self.procs = [], {}, [], []
        self.seq = 0
        self.windows = load_windows(args.session)
        self.index = Counter()
        config = self.tmp / "broker.yaml"
        config.write_text(f"""listeners:
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
        self.broker_config = config
        self.broker = None

    def env(self, **extra):
        return {**os.environ, "PROJECT_ID": PROJECT, "MQTT_HOST": "127.0.0.1", "MQTT_PORT": str(self.mqtt_port), "MQTT_TLS": "false",
                "ALLOW_INSECURE_LOCAL": "true", "CUCI_MODE": "demo", "CUCI_START_S": "3", "CUCI_DONE_S": "15", "CUCI_DONE_NOSPIN_S": "15",
                "CUCI_REMIND_S": "60", "CUCI_SENSOR_LOST_S": "40", "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
                "DASHBOARD_PORT": str(self.dash_port), "MQTT_WS_URL": f"ws://127.0.0.1:{self.ws_port}/mqtt", **extra}

    def spawn(self, name, *cmd, **env):
        log = open(self.tmp / f"{name}.log", "a")
        p = subprocess.Popen([sys.executable, *cmd], cwd=ROOT, env=self.env(**env), stdout=log, stderr=subprocess.STDOUT)
        p.log_path = self.tmp / f"{name}.log"
        self.procs.append(p)
        return p

    def start_broker(self):
        self.broker = subprocess.Popen(["amqtt", "-c", str(self.broker_config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(75):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", self.mqtt_port)) == 0:
                    return
            time.sleep(0.2)
        raise RuntimeError("Broker tidak hidup")

    def stop_broker(self):
        self.broker.kill()
        self.broker.wait()

    def listen(self):
        c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id="demo-listener")
        c.reconnect_delay_set(1, 2)
        c.on_connect = lambda cl, u, f, r, p: cl.subscribe([(PREFIX + t, 1) for t in ("status", "alerts", "alert_state")])
        c.on_message = lambda cl, u, m: self.msgs.append((time.time(), m.topic.rsplit("/", 1)[1], json.loads(m.payload)))
        c.connect_async("127.0.0.1", self.mqtt_port, keepalive=30)
        c.loop_start()
        self.client = c
        for _ in range(50):
            if c.is_connected():
                return
            time.sleep(0.2)
        raise RuntimeError("Listener tidak tersambung")

    def bodies(self, topic, since=0.0):
        return [m[2] for m in list(self.msgs) if m[1] == topic and m[0] >= since]

    def wait(self, check, timeout):
        end = time.time() + timeout
        while time.time() < end:
            if check():
                return True
            time.sleep(0.2)
        return False

    def send_window(self, label, v1=False, rms=None):
        if rms is not None:
            t = Telemetry.make("edge1", "demo", self.seq, rms, 0.6 if rms > 2 else 0.0, {"data_source": "synthetic_replay"})
        else:
            items = self.windows[label]
            w = items[self.index[label] % len(items)]
            self.index[label] += 1
            t = Telemetry.make("edge1", "demo", self.seq, w["motion_rms"], w["rotation_rad"], {**telemetry_extra(w), "data_source": "synthetic_replay"})
        self.sent_at[self.seq] = time.time()
        self.client.publish(f"{PREFIX}edge/edge1/telemetry", t.to_json(), qos=1)
        self.seq += 1

    def feed(self, label, seconds, stop=None):
        end = time.time() + seconds
        while time.time() < end:
            self.send_window(label)
            time.sleep(1)
            if stop and stop():
                return True
        return False

    def shake(self):
        """Goyangan beruntun. hp_pemilik.py simulator ikut mengirim edge2 diam di sela-selanya dan dapat memutus
        hitungan dua jendela berurutan, jadi goyangan diulang sampai detector menjawab. Ini artefak dua pengirim pada demo."""
        for _ in range(10):
            for _ in range(2):
                t = Telemetry.make("edge2", "demo", self.seq, 6.0, 0.8, {"data_source": "synthetic_replay"})
                self.seq += 1
                self.client.publish(f"{PREFIX}edge/edge2/telemetry", t.to_json(), qos=1)
                time.sleep(0.05)
            time.sleep(0.5)
            if self.bodies("status")[-1]["status"] == "IDLE":
                return

    def check(self, code, what, ok, evidence=""):
        self.results.append({"scenario": code, "check": what, "pass": bool(ok), "evidence": str(evidence)})
        print(f"[{'LULUS' if ok else 'GAGAL'}] {code}: {what} {evidence}", flush=True)

    def resource(self, pid):
        ticks = os.sysconf("SC_CLK_TCK")
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        cpu = (int(stat[11]) + int(stat[12])) / ticks
        rss = next(l for l in Path(f"/proc/{pid}/status").read_text().splitlines() if l.startswith("VmHWM"))
        return cpu, int(rss.split()[1]) / 1024

    def latency_summary(self, statuses_from):
        values = []
        for t, topic, b in list(self.msgs):
            if topic == "status" and t >= statuses_from and b.get("device_id") == "edge1" and b.get("sequence") in self.sent_at:
                values.append((t - self.sent_at[b["sequence"]]) * 1000)
        return values

    def run(self):
        a = self.args
        self.start_broker()
        self.listen()
        state_path = str(self.tmp / "state.json")
        model_env = dict(DETECTION_MODE="HYBRID", MODEL_PATH=str(a.model), ALLOW_SYNTHETIC_MODEL="true", DETECTOR_STATE_PATH=state_path)
        detector = self.spawn("detector", "detector.py", **model_env)
        started = time.time()
        owner = self.spawn("hp_b", "hp_pemilik.py", "--source", "simulator", "--scenario", "still")
        self.wait(lambda: self.bodies("status"), 20)
        first = self.bodies("status")[0]
        self.check("MODE", "HYBRID aktif dengan model sintetis berlabel", first.get("effective_mode") == "HYBRID" and first.get("model_data_kind") == "synthetic",
                   f"{first.get('effective_mode')} / {first.get('model_version')}")
        page, browser = self.open_browser()

        # A
        self.feed("IDLE", 8)
        self.check("A", "Mesin IDLE", self.bodies("status")[-1]["status"] == "IDLE", self.bodies("status")[-1]["status"])
        self.ui(page, "A", "status", "IDLE", "a_idle")
        self.ui(page, "A", "banners", "MODEL PENGEMBANGAN")
        self.ui(page, "A", "banners", "MODE SIMULASI")
        # B
        t0 = time.time()
        self.feed("WASHING", 35)
        st = self.bodies("status", t0)
        self.check("B", "Mesin WASHING", any(b["status"] == "WASHING" for b in st), Counter(b["status"] for b in st))
        self.check("B", "Prediksi model benar-benar memengaruhi aktivitas", any(b.get("activity_source") == "model" for b in st),
                   Counter(b.get("activity_source") for b in st))
        # Pembanding adalah status detector terakhir: model dapat salah kelas, dan dashboard wajib menampilkan apa adanya.
        self.ui(page, "B", "status", self.bodies("status")[-1]["status"], "b_washing")
        if page:
            before = page.evaluate("document.getElementById('chart-rms').toDataURL()")
            self.feed("WASHING", 3)
            page.wait_for_timeout(1200)
            self.check("B", "Dashboard: grafik sensor berubah", before != page.evaluate("document.getElementById('chart-rms').toDataURL()"))
        # C
        t0 = time.time()
        self.feed("SPIN", 30)
        st = self.bodies("status", t0)
        self.check("C", "Mesin SPIN", any(b["status"] == "SPIN" for b in st), Counter(b["status"] for b in st))
        spin_by_model = any(b.get("activity") == "SPIN" and b.get("activity_source") == "model" for b in st)
        self.check("C", "Model mengidentifikasi SPIN", spin_by_model)
        self.ui(page, "C", "ai-activity", "SPIN", "c_spin")
        self.ui(page, "C", "path", "SPIN")
        # D
        t0 = time.time()
        self.feed("IDLE", 8)
        self.feed("WASHING", 25)
        self.check("D", "Berhenti sementara tidak memicu DONE", not self.bodies("alerts", started) and self.bodies("status")[-1]["status"] != "DONE",
                   self.bodies("status")[-1]["status"])
        if page:
            self.check("D", "Dashboard: belum menampilkan DONE saat jeda", page.text_content("#status") != "DONE" and not page.is_visible("#alert-active"), page.text_content("#status"))
            self.shot(page, "d_pause")
        # E
        got = self.feed("IDLE", 180, stop=lambda: self.bodies("alerts"))
        alert = self.bodies("alerts")[0] if got else {}
        self.check("E", "Selesai dan alert terkirim", got and alert.get("event") == "laundry_done", alert.get("kind"))
        self.wait(lambda: "ALARM" in owner.log_path.read_text(), 8)
        self.check("E", "HP B (proses nyata, sensor simulator) menjalankan alarm", "ALARM" in owner.log_path.read_text())
        self.ui(page, "E", "status", "DONE")
        self.ui(page, "E", "alert-state", "menunggu konfirmasi", "e_done_alert")
        self.feed("IDLE", 5)
        self.check("E", "Tidak ada alert duplikat", len(self.bodies("alerts")) == 1, len(self.bodies("alerts")))
        # F
        self.shake()
        ok = self.wait(lambda: self.bodies("status")[-1]["status"] == "IDLE" and "konfirmasi" in self.bodies("status")[-1]["reason"], 10)
        self.check("F", "Goyangan HP B mengembalikan IDLE", ok, self.bodies("status")[-1]["reason"])
        ok = self.wait(lambda: self.bodies("alert_state") and self.bodies("alert_state")[-1]["active"] is False, 5)
        self.check("F", "alert_state bersih dan notifikasi dihapus", ok and self.wait(lambda: "notifikasi dihapus" in owner.log_path.read_text(), 5))
        self.ui(page, "F", "alerts", "Dikonfirmasi pemilik", "f_ack")
        # I + H
        count = len(self.bodies("alerts"))
        t0 = time.time()
        self.feed("WASHING", 25)
        self.check("I", "Siklus kedua dimulai", any(b["status"] in ("WASHING", "SPIN") for b in self.bodies("status", t0)), self.bodies("status")[-1]["status"])
        self.stop_broker()
        self.ui(page, "H", "conn", "Terputus", "g_broker_down", timeout=15)
        self.ui(page, "H", "door-note", "Broker terputus")
        time.sleep(4)
        self.start_broker()
        self.ui(page, "H", "conn", "Tersambung", timeout=25)
        self.wait(self.client.is_connected, 20)
        t0 = time.time()
        self.feed("WASHING", 6)
        st = self.bodies("status", t0)
        self.check("H", "State siklus bertahan setelah broker restart", any(b["status"] in ("WASHING", "SPIN") for b in st) and detector.poll() is None, st[-1]["status"] if st else "tanpa status")
        self.feed("SPIN", 15)
        got = self.feed("IDLE", 180, stop=lambda: len(self.bodies("alerts")) > count)
        self.check("I", "Siklus kedua menghasilkan alert baru", got, len(self.bodies("alerts")))
        self.shake()
        self.wait(lambda: self.bodies("status")[-1]["status"] == "IDLE", 10)

        # J dashboard selagi model masih aktif
        config = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.dash_port}/config.json", timeout=5).read())
        self.check("J", "Dashboard melayani konfigurasi tanpa kredensial", "password" not in json.dumps(config).lower() and config.get("project_id", PROJECT) == PROJECT, list(config))
        self.check_browser(page, "HYBRID")

        statuses = self.latency_summary(started)
        alert_latency = [(t - b["detected_at_ms"] / 1000) * 1000 for t, topic, b in list(self.msgs) if topic == "alerts"]
        cpu, peak = self.resource(detector.pid)
        elapsed = time.time() - started
        latencies = [b["inference_latency_ms"] for b in self.bodies("status") if "inference_latency_ms" in b]
        self.metrics = {
            "inference_latency_ms": {"n": len(latencies), "median": statistics.median(latencies), "max": max(latencies)} if latencies else None,
            "telemetry_to_status_ms_local_broker": {"n": len(statuses), "median": round(statistics.median(statuses), 1), "p95": round(statistics.quantiles(statuses, n=20)[18], 1)} if len(statuses) > 20 else None,
            "alert_publish_to_receive_ms_local_broker": [round(x, 1) for x in alert_latency],
            "detector_cpu_percent_one_core": round(100 * cpu / elapsed, 2), "detector_peak_rss_mb": round(peak, 1), "seconds_observed": round(elapsed),
            "completion_alerts": sum(b.get("kind") in ("completed_after_spin", "stopped_without_spin") for b in self.bodies("alerts")),
            "cycles_fed": 2}

        # G: model rusak, detector restart
        detector.terminate()
        detector.wait(timeout=10)
        bad = self.tmp / "model_rusak"
        shutil.copytree(a.model, bad)
        with open(bad / "model.joblib", "ab") as f:
            f.write(b"rusak")
        t0 = time.time()
        Path(state_path).unlink(missing_ok=True)
        detector = self.spawn("detector", "detector.py", DETECTION_MODE="HYBRID", MODEL_PATH=str(bad), ALLOW_SYNTHETIC_MODEL="true")
        self.wait(lambda: any(b.get("fallback_reason") for b in self.bodies("status", t0)), 20)
        fb = next((b for b in self.bodies("status", t0) if b.get("fallback_reason")), {})
        self.check("G", "Model rusak ditolak dan fallback terlihat", (fb.get("effective_mode"), fb.get("fallback_reason")) == ("RULE_ONLY", "model_hash_mismatch"), fb.get("fallback_reason"))
        count = len(self.bodies("alerts"))
        for _ in range(8):
            self.send_window("", rms=3.0)
            time.sleep(1)
        self.check("G", "Fallback tidak memicu DONE saat mesin aktif", len(self.bodies("alerts")) == count, self.bodies("status")[-1]["status"])
        got = False
        for _ in range(30):
            self.send_window("", rms=0.0)
            time.sleep(1)
            if len(self.bodies("alerts")) > count:
                got = True
                break
        self.check("G", "Siklus penuh tetap berjalan dengan aturan", got)
        self.check_browser(page, "RULE_ONLY")
        self.ui(page, "G", "banners", "Model tidak dipakai", "h_fallback")
        self.ui(page, "G", "ai-fallback", "file model berubah atau rusak")
        if page:
            page.click("#btn-disarm")
            page.click("#btn-disarm-yes")
            self.ui(page, "J", "cmd-feedback", "Detector mengonfirmasi DISARM", "i_disarm")
            self.ui(page, "J", "status", "DISARMED")
            page.click("#btn-arm")
            self.ui(page, "J", "cmd-feedback", "Detector mengonfirmasi ARM")
            self.mobile(browser)
            browser.close()
        self.play.stop() if page else None

    def open_browser(self):
        if not self.args.browser:
            self.check("J", "Dashboard browser", True, "TIDAK DIJALANKAN: --browser tidak diberikan")
            return None, None
        from playwright.sync_api import sync_playwright
        self.play = sync_playwright().start()
        browser = self.play.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=2)
        self.page_errors = []
        page.on("pageerror", lambda e: self.page_errors.append(e.message))
        for _ in range(30):
            try:
                page.goto(f"http://127.0.0.1:{self.dash_port}/")
                break
            except Exception:
                time.sleep(0.5)
        return page, browser

    def shot(self, page, name):
        folder = self.args.out / "screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(folder / f"{name}.png"), full_page=True)

    def ui(self, page, code, element, expected, shot=None, timeout=10):
        """Memeriksa isi DOM dashboard, yang hanya berubah jika pesan dari detector sampai ke browser."""
        if not page:
            return
        end = time.time() + timeout
        value = ""
        while time.time() < end:
            value = page.text_content("#" + element) or ""
            if expected in value:
                break
            page.wait_for_timeout(200)
        self.check(code, f"Dashboard: #{element} memuat {expected}", expected in value, value[:80])
        if shot:
            page.wait_for_timeout(600)
            self.shot(page, shot)

    def check_browser(self, page, mode):
        if not page:
            return
        self.ui(page, "J", "effective-mode", mode)
        self.check("J", "Dashboard tanpa galat JavaScript", not self.page_errors, self.page_errors)

    def mobile(self, browser):
        context = browser.new_context(**self.play.devices["Pixel 5"])
        phone = context.new_page()
        phone.set_viewport_size({"width": 360, "height": 740})
        phone.goto(f"http://127.0.0.1:{self.dash_port}/")
        phone.wait_for_timeout(2500)
        for _ in range(3):
            self.send_window("", rms=0.0)
            time.sleep(1)
        phone.wait_for_timeout(1000)
        sizes = phone.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
        self.check("J", "Lebar ponsel 360 piksel tanpa scroll horizontal (emulasi)", sizes[0] <= sizes[1] and phone.text_content("#status") not in ("Memuat", ""), sizes)
        self.shot(phone, "j_mobile")
        context.close()

    def finish(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait()
        if self.broker and self.broker.poll() is None:
            self.broker.kill()
        self.args.out.mkdir(parents=True, exist_ok=True)
        events = [l for l in (self.tmp / "detector.log").read_text().splitlines() if l.startswith("[EVENT]")] if (self.tmp / "detector.log").exists() else []
        (self.args.out / "e2e_events.log").write_text("\n".join(events) + "\n")
        report = {"evidence_class": "SIMULATION", "note": "Broker lokal dan telemetri sintetis. Bukan hardware validation.",
                  "passed": sum(r["pass"] for r in self.results), "total": len(self.results), "results": self.results, "metrics": getattr(self, "metrics", None)}
        (self.args.out / "e2e_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(json.dumps({k: report[k] for k in ("passed", "total", "metrics")}, indent=1))
        return report["passed"] == report["total"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--session", type=Path, default=ROOT / "data/synthetic/SYNTHETIC_SYNM1_C04")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "reports/e2e")
    args = parser.parse_args()
    demo = Demo(args)
    try:
        demo.run()
    finally:
        ok = demo.finish()
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
