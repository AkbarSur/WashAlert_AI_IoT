"""Common edge pipeline, the same for protected and owner phones.

Real sensor -> two feature extractions -> MQTT Cloud. Simulator is opt-in
and MUST NOT be described as a real IoT physical-edge demonstration.
"""

import argparse
import json
import queue
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable

from shared.features import InvalidWindow, compute_window_features, telemetry_extra
from shared.alarm import clear_alarm
from shared.messages import Telemetry, parse_alert
from shared.mqtt_connection import create_client, topic
from shared.sensors import select_source

AlertHandler = Callable[[dict], None]


class AlertReceiver:
    """Validasi, dedupe, dan pemanggilan alarm di thread sendiri agar MQTT tidak tertahan."""

    def __init__(self, on_alert: AlertHandler, on_clear: Callable[[], None] = clear_alarm, clock=time.time, log=print, worker: bool = True):
        self.on_alert, self.on_clear, self.clock, self.log = on_alert, on_clear, clock, log
        self.seen = deque(maxlen=64)
        self.active_id = None
        self.jobs = queue.Queue()
        if worker:
            threading.Thread(target=self._run, name="washalert-alarm", daemon=True).start()
        self.worker = worker

    def _run(self):
        while True:
            self._execute(*self.jobs.get())

    def _execute(self, fn, args):
        try:
            fn(*args)
        except Exception as exc:  # alarm gagal tidak boleh mematikan edge
            self.log(f"[ALARM] Gagal: {exc}")

    def _submit(self, fn, *args):
        if self.worker:
            self.jobs.put((fn, args))
        else:
            self._execute(fn, args)

    def handle_alert(self, payload) -> bool:
        try:
            alert = parse_alert(payload, int(self.clock() * 1000))
        except ValueError as exc:
            self.log(f"[ALERT] Diabaikan: {exc}")
            return False
        alert_id = alert.get("alert_id")
        if alert_id in self.seen:
            return False
        if alert_id:
            self.seen.append(alert_id)
        self._submit(self.on_alert, alert)
        return True

    def handle_state(self, payload) -> bool:
        """alert_state retained: menyusul alert saat baru tersambung, dan menghapus notifikasi."""
        try:
            state = json.loads(payload)
            if not isinstance(state, dict) or type(state.get("active")) is not bool:
                raise ValueError("alert_state tidak valid")
        except ValueError as exc:
            self.log(f"[ALERT] Diabaikan: {exc}")
            return False
        if state["active"]:
            self.active_id = state.get("alert_id")
            return self.handle_alert(payload)
        if self.active_id is not None:
            self.active_id = None
            self._submit(self.on_clear)
        return True


def publish_when_connected(client, topic_name: str, payload: str, wait_s: float = 10) -> bool:
    """Terbitkan telemetri jika tersambung. Saat koneksi putus, jendela dibuang:
    telemetri lama tidak berguna dan detector akan menolaknya sebagai stale."""
    if not client.is_connected():
        return False
    try:
        info = client.publish(topic_name, payload, qos=1)
        info.wait_for_publish(timeout=wait_s)
    except (RuntimeError, ValueError) as exc:
        print(f"[MQTT] Publish gagal, jendela dibuang: {exc}", flush=True)
        return False
    return True


def _parse_args(device_id: str, default_scenario: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"WashAlert {device_id}")
    parser.add_argument(
        "--source", choices=["android", "simulator"], default="android",
        help="Default: sensor Android asli. Simulator hanya untuk pengujian.",
    )
    parser.add_argument(
        "--scenario", choices=["still", "washer", "ack"], default=default_scenario,
        help="Hanya dipakai dengan --source simulator",
    )
    parser.add_argument("--interval", type=float, default=None)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument(
        "--debug-sensors", action="store_true",
        help="Print raw accelerometer/gyroscope values before processing.",
    )
    args = parser.parse_args()
    if args.interval is None:
        args.interval = 0.1 if args.source == "android" else 0.35
    if args.interval <= 0 or args.samples < 2:
        parser.error("--interval must be positive and --samples >= 2")
    return args


def run_edge(device_id: str, on_alert: AlertHandler | None = None, default_scenario: str = "still"):
    args = _parse_args(device_id, default_scenario)
    label = device_id.upper()
    source = select_source(args.source, args.scenario)
    client = create_client(device_id, blocking=False)

    if on_alert is not None:
        receiver = AlertReceiver(on_alert)
        state_topic = topic("alert_state")

        def on_connect(client, userdata, flags, reason_code, properties):
            if reason_code.is_failure:
                print(f"[{label}] MQTT connection rejected: {reason_code}")
                return
            client.subscribe([(topic("alerts"), 1), (state_topic, 1)])
            print(f"[{label}] Subscribed to {topic('alerts')}")

        def on_message(client, userdata, message):
            if message.topic == state_topic:
                receiver.handle_state(message.payload)
            else:
                receiver.handle_alert(message.payload)

        client.on_connect = on_connect
        client.on_message = on_message

    client.loop_start()
    boot_id = uuid.uuid4().hex
    sequence = 0
    dropped = 0
    telemetry_topic = topic(f"edge/{device_id}/telemetry")
    print(f"[{label}] Source: {args.source}")
    print(f"[{label}] Publishes to: {telemetry_topic}")

    try:
        while True:
            samples = []
            for sample_index in range(args.samples):
                sample = source.read()
                samples.append(sample)
                if args.debug_sensors:
                    print(
                        f"[{label} | RAW] accel={sample.acceleration} m/s² "
                        f"gyro={sample.gyroscope} rad/s",
                        flush=True,
                    )
                if sample_index < args.samples - 1:
                    time.sleep(args.interval)
            try:
                window = compute_window_features(samples)
            except InvalidWindow as exc:
                print(f"[{label}] Jendela tidak valid, tidak diterbitkan: {exc}", flush=True)
                continue
            telemetry = Telemetry.make(
                device_id, boot_id, sequence,
                window["motion_rms"], window["rotation_rad"],
                extra={**telemetry_extra(window, bool(getattr(source, "sensor_fault", False))), "data_source": args.source},
            )
            if publish_when_connected(client, telemetry_topic, telemetry.to_json()):
                if dropped:
                    print(f"[{label}] Tersambung lagi, {dropped} jendela terbuang selama putus", flush=True)
                    dropped = 0
                print(
                    f"[{label}] #{sequence} "
                    f"motion={window['motion_rms']:.3f} m/s², "
                    f"rotation={window['rotation_rad']:.3f} rad"
                )
            else:
                if dropped == 0:
                    print(f"[{label}] MQTT belum tersambung, jendela dibuang sampai pulih", flush=True)
                dropped += 1
            sequence += 1
    except KeyboardInterrupt:
        print(f"[{label}] Stopped")
    finally:
        client.loop_stop()
        client.disconnect()
