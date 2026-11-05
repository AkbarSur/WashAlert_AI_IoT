"""NODE 3: detector WashAlert. Subscribe MQTT, jalankan state machine, kirim alert.

Topik (prefix washalert/<PROJECT_ID>/):
  subscribe  edge/+/telemetry      telemetri HP A (mesin) dan HP B (pemilik)
  subscribe  control               ARM / DISARM dari pemilik
  publish    alerts                saat cucian selesai + pengingat (HP B bergetar)
  publish    alert_state (retained) keadaan alert terakhir untuk HP B yang baru tersambung
  publish    status (retained)     status terbaru untuk dashboard
"""

import json
import os
import threading
import time
import uuid

from dotenv import load_dotenv

from nodes.detector_service import state_store
from nodes.detector_service.activity import make_activity_source
from nodes.detector_service.rules import Config, Decision, WasherDetector
from shared.messages import Telemetry, alert_json, status_json
from shared.mqtt_connection import create_client, topic

REJECT_STATUS_INTERVAL_MS = 5000


def build_detector() -> tuple:
    """(detector, info mode). DETECTION_MODE tidak dikenal menghentikan start dengan pesan jelas."""
    cfg = Config.from_env()
    mode = os.getenv("DETECTION_MODE", "RULE_ONLY").strip().upper()
    source, info = make_activity_source(mode, os.getenv("MODEL_PATH", "").strip() or None, cfg,
                                        os.getenv("ALLOW_SYNTHETIC_MODEL", "false").lower() == "true")
    return WasherDetector(cfg, activity_source=source), info


class DetectorService:
    """Jembatan MQTT dan WasherDetector. Semua akses detector dilindungi satu lock."""

    def __init__(self, client, detector: WasherDetector, info: dict, clock=time.time, log=print, state_path: str | None = None):
        self.state_path = state_path
        self.saved_signature = None
        self.last_event_key = None
        self.client, self.detector, self.info, self.clock, self.log = client, detector, info, clock, log
        self.lock = threading.Lock()
        self.status_topic = topic("status")
        self.telemetry_topic = topic("edge/+/telemetry")
        self.control_topic = topic("control")
        self.alert_topic = topic("alerts")
        self.alert_state_topic = topic("alert_state")
        self.rejected_schema = 0
        self.active_alert = None
        self.last_alert_id = None
        self.alert_ended_by = None   # acknowledged | superseded | disarmed
        self.connected_once = False
        self.last_reject_status = 0

    def now_ms(self) -> int:
        return int(self.clock() * 1000)

    def event(self, name: str, **fields):
        """Log terstruktur satu baris JSON, untuk kejadian penting. Log manusia tetap ada."""
        self.log("[EVENT] " + json.dumps({"event": name, "t_ms": self.now_ms(), **fields}, sort_keys=True))

    def restore_state(self):
        if not self.state_path:
            return
        try:
            saved = state_store.load(self.state_path, self.now_ms())
            if saved is None:
                return
            with self.lock:
                self.detector.restore(saved["detector"], self.now_ms())
                self.active_alert = saved.get("active_alert")
                self.connected_once = True
            self.event("state_restored", state=self.detector.state, armed=self.detector.armed)
        except (ValueError, KeyError, TypeError) as exc:
            self.event("state_restore_failed", error=str(exc))

    def persist(self):
        if not self.state_path:
            return
        with self.lock:
            body = {"detector": self.detector.snapshot(), "active_alert": self.active_alert}
        signature = json.dumps(body, sort_keys=True)
        if signature == self.saved_signature:
            return
        try:
            state_store.save(self.state_path, body, self.now_ms())
            self.saved_signature = signature
        except OSError as exc:
            self.event("state_save_failed", error=str(exc))

    def _extra(self, decision: Decision | None) -> dict:
        d = self.detector
        extra = dict(self.info)
        disabled = getattr(d.source, "disabled_reason", None)
        if disabled:  # model gagal saat berjalan: status tidak boleh tetap mengaku ML aktif
            extra.update(effective_mode="RULE_ONLY", model_status="failed", fallback_reason=disabled)
        latency = getattr(d.source, "last_latency_ms", None)
        if latency is not None:
            extra["inference_latency_ms"] = latency
        if decision is not None and decision.activity is not None:
            extra.update(activity=decision.activity, activity_source=decision.activity_source, classified_at_ms=decision.classified_at_ms)
            if decision.probability is not None:
                extra["model_probability"] = decision.probability
            if decision.source_reason:
                extra["activity_reason"] = decision.source_reason
        if decision is not None and decision.alert_kind:
            extra["alert_kind"] = decision.alert_kind
        elif d.alert_kind:
            extra["alert_kind"] = d.alert_kind
        reading = d.latest.get("edge1")
        sensor = {"lost": d.sensor_lost}
        if reading is not None and reading.extra:
            sensor.update(actual_hz=reading.extra["actual_hz"], stale_count=reading.extra["stale_count"], fault=reading.extra["sensor_fault"])
        extra["sensor"] = sensor
        extra["spin_seen"] = d.spin_seen
        extra["rejected"] = {**d.rejected, "schema": self.rejected_schema}
        return extra

    def publish_status(self, status: str, reason: str, decision: Decision | None = None, reading: Telemetry | None = None,
                       last_command: str | None = None):
        payload = status_json(status, reason, self.detector.armed,
                              run_minutes=decision.run_minutes if decision else 0.0,
                              avg_rms=decision.avg_rms if decision else 0.0,
                              device_id=reading.device_id if reading else None,
                              sequence=reading.sequence if reading else None,
                              extra={**self._extra(decision), **({"last_command": last_command} if last_command else {})})
        self.client.publish(self.status_topic, payload, qos=1, retain=True)

    def publish_alert_state(self):
        alert = self.active_alert
        body = alert if alert else {"active": False, "alert_id": self.last_alert_id, "ended_by": self.alert_ended_by,
                                    "updated_at_ms": self.now_ms()}
        self.client.publish(self.alert_state_topic, json.dumps(body), qos=1, retain=True)

    def apply(self, decision: Decision, reading: Telemetry | None = None):
        """Menerbitkan hasil keputusan. Dipanggil di luar lock."""
        key = (decision.status, decision.activity_source, decision.source_reason)
        if decision.publish and key != self.last_event_key:
            self.last_event_key = key
            self.event("state", status=decision.status, activity=decision.activity, source=decision.activity_source, source_reason=decision.source_reason)
        if decision.publish:
            self.publish_status(decision.status, decision.reason, decision, reading)
        # Keadaan lama dihapus lebih dulu, agar HP B tidak menghapus notifikasi koreksi yang baru.
        if decision.clear_alert and self.active_alert:
            self.last_alert_id = self.active_alert["alert_id"]
            self.alert_ended_by = "superseded" if decision.alert_kind == "correction" else "acknowledged"
            self.active_alert = None
            self.publish_alert_state()
        if decision.alert:
            now = self.now_ms()
            kind = decision.alert_kind or "completed_after_spin"
            alert_id = uuid.uuid4().hex
            valid_for = int(2 * self.detector.cfg.remind_s + 60)
            self.client.publish(self.alert_topic, alert_json(decision.run_minutes, decision.reason, now, alert_id, kind, decision.is_reminder, valid_for), qos=1, retain=False)
            self.log(f"[DETECTOR] >>> ALERT {kind} dikirim ke HP B")
            self.event("alert", alert_id=alert_id, kind=kind, is_reminder=decision.is_reminder)
            if kind in ("completed_after_spin", "stopped_without_spin"):
                self.active_alert = {"active": True, "event": "laundry_done", "alert_id": alert_id, "kind": kind, "reason": decision.reason,
                                     "run_minutes": decision.run_minutes, "detected_at_ms": now, "updated_at_ms": now, "valid_for_s": valid_for}
                self.publish_alert_state()

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self.log(f"[DETECTOR] Koneksi MQTT ditolak: {reason_code}")
            return
        client.subscribe([(self.telemetry_topic, 1), (self.control_topic, 1)])
        self.log(f"[DETECTOR] Subscribe: {self.telemetry_topic} dan {self.control_topic}")
        with self.lock:
            if self.connected_once:   # state siklus tetap di memori selama broker putus
                current = self.detector._decision(self.now_ms(), "Tersambung kembali ke broker")
                self.publish_status(current.status, current.reason, current)
            else:
                self.publish_status("ONLINE", "Detector berjalan")
            self.connected_once = True
            self.publish_alert_state()

    def handle_control(self, payload: bytes):
        command = payload.decode(errors="replace").strip().upper()
        if command not in ("ARM", "DISARM"):
            self.log(f"[DETECTOR] Perintah tidak dikenal: {command[:40]}")
            return
        with self.lock:
            self.detector.set_armed(command == "ARM")
            status = self.detector.public_status()
            if command == "DISARM" and self.active_alert:
                self.last_alert_id = self.active_alert["alert_id"]
                self.alert_ended_by = "disarmed"
                self.active_alert = None
        self.log(f"[DETECTOR] Perintah pemilik: {command}")
        self.publish_status(status, f"Pemilik mengirim {command}", last_command=command)
        if command == "DISARM":
            self.publish_alert_state()
        self.persist()

    def on_message(self, client, userdata, message):
        try:
            self._handle(message)
        except Exception as exc:  # satu pesan tidak boleh mematikan layanan
            self.log(f"[DETECTOR] Galat saat memproses pesan: {exc!r}")

    def _handle(self, message):
        if message.topic == self.control_topic:
            self.handle_control(message.payload)
            return
        try:
            reading = Telemetry.from_json(message.payload)
            if message.topic != topic(f"edge/{reading.device_id}/telemetry"):
                self.rejected_schema += 1
                self.log("[DETECTOR] DITOLAK: topik dan device ID tidak cocok")
                return
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.rejected_schema += 1
            self.log(f"[DETECTOR] DITOLAK payload rusak: {exc}")
            return
        with self.lock:
            decision = self.detector.accept(reading, self.now_ms())
        self.log(f"[DETECTOR] {reading.device_id} #{reading.sequence} rms={reading.motion_rms:.3f} avg={decision.avg_rms:.3f}: "
                 f"{decision.status} — {decision.reason}")
        if decision.status.startswith("REJECTED_"):
            if self.now_ms() - self.last_reject_status >= REJECT_STATUS_INTERVAL_MS:
                self.last_reject_status = self.now_ms()
                with self.lock:
                    current = self.detector._decision(self.now_ms(), f"Telemetri ditolak: {decision.reason}")
                self.publish_status(current.status, current.reason, current)
            return
        self.apply(decision, reading)
        self.persist()

    def tick(self):
        with self.lock:
            decision = self.detector.tick(self.now_ms())
        if decision is not None:
            self.log(f"[DETECTOR] tick: {decision.status} — {decision.reason}")
            self.apply(decision)
            self.persist()


def main():
    load_dotenv()
    try:
        detector, info = build_detector()
    except ValueError as exc:
        raise SystemExit(f"[DETECTOR] Konfigurasi ditolak: {exc}") from exc
    print(f"[DETECTOR] Mode diminta {info['detection_mode']}, mode efektif {info['effective_mode']}"
          + (f", fallback: {info['fallback_reason']}" if info.get("fallback_reason") else ""), flush=True)
    if info.get("model_data_kind") == "synthetic":
        print("[DETECTOR] PERINGATAN: MODEL SINTETIS, MODE EKSPERIMEN. Bukan bukti performa pada mesin cuci.", flush=True)
    if os.getenv("CUCI_MODE", "demo").lower() == "real" and not os.getenv("CUCI_DONE_S"):
        print("[DETECTOR] PERINGATAN: CUCI_DONE_S belum ditetapkan dari analisis jeda. Alert palsu saat rendam masih mungkin.", flush=True)

    status_topic = topic("status")
    offline = status_json("OFFLINE", "Detector terputus", armed=False)
    client = create_client("detector", will=(status_topic, offline), blocking=False)
    service = DetectorService(client, detector, info, log=lambda *a: print(*a, flush=True),
                              state_path=os.getenv("DETECTOR_STATE_PATH", "").strip() or None)
    service.restore_state()
    service.event("startup", **info)
    client.on_connect = service.on_connect
    client.on_message = service.on_message
    print("[DETECTOR] Mulai. Ctrl+C untuk berhenti", flush=True)
    client.loop_start()
    try:
        while True:
            time.sleep(1)
            try:
                service.tick()
            except Exception as exc:
                print(f"[DETECTOR] Galat tick: {exc!r}", flush=True)
    except KeyboardInterrupt:
        print("[DETECTOR] Berhenti")
    finally:
        try:
            info_msg = client.publish(status_topic, status_json("OFFLINE", "Detector dihentikan", armed=False), qos=1, retain=True)
            info_msg.wait_for_publish(timeout=3)
        except (RuntimeError, ValueError):
            pass
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
