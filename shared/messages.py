"""MQTT message schema: the contract between the two edge nodes and detector."""

from dataclasses import asdict, dataclass, field
import json
import math
import time


# Field opsional telemetri v2. Nilai numerik harus finite dan tidak negatif.
V2_NUMERIC_FIELDS = (
    "window_s", "n_samples", "actual_hz", "stale_count",
    "acc_dyn_rms", "acc_mag_ptp", "gyro_rms", "gyro_max",
)


@dataclass(frozen=True)
class Telemetry:
    device_id: str
    boot_id: str
    sequence: int
    sent_at_ms: int
    motion_rms: float
    rotation_rad: float
    extra: dict | None = field(default=None, hash=False)  # field v2, None untuk v1

    def to_json(self) -> str:
        body = asdict(self)
        extra = body.pop("extra")
        if extra:
            body.update(extra)
        return json.dumps(body)

    @staticmethod
    def from_json(payload: str | bytes) -> "Telemetry":
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise ValueError("Telemetry must be a JSON object")
        for key in ("device_id", "boot_id"):
            if not isinstance(value.get(key), str) or not value[key]:
                raise ValueError(f"Invalid {key}")
        if value["device_id"] not in ("edge1", "edge2"):
            raise ValueError("Unknown edge device")
        sequence = value.get("sequence")
        timestamp = value.get("sent_at_ms")
        if type(sequence) is not int or sequence < 0:
            raise ValueError("Invalid sequence")
        if type(timestamp) is not int or timestamp < 0:
            raise ValueError("Invalid timestamp")
        features = []
        for key in ("motion_rms", "rotation_rad"):
            number = value.get(key)
            if type(number) not in (float, int) or not math.isfinite(number) or number < 0:
                raise ValueError(f"Invalid {key}")
            features.append(float(number))
        return Telemetry(value["device_id"], value["boot_id"], sequence, timestamp, *features,
                         extra=_parse_v2(value))

    @staticmethod
    def make(device_id: str, boot_id: str, sequence: int, motion_rms: float, rotation_rad: float,
             extra: dict | None = None) -> "Telemetry":
        return Telemetry(device_id, boot_id, sequence, int(time.time() * 1000), motion_rms, rotation_rad, extra)


def _parse_v2(value: dict) -> dict | None:
    """Validasi field v2. Pesan v1 atau versi tak dikenal diperlakukan sebagai v1."""
    if value.get("schema_version") != 2:
        return None
    extra = {"schema_version": 2}
    for key in V2_NUMERIC_FIELDS:
        number = value.get(key)
        if type(number) not in (float, int) or not math.isfinite(number) or number < 0:
            raise ValueError(f"Invalid {key}")
        extra[key] = number
    if type(value.get("sensor_fault")) is not bool:
        raise ValueError("Invalid sensor_fault")
    extra["sensor_fault"] = value["sensor_fault"]
    return extra


def status_json(status: str, reason: str, armed: bool, run_minutes: float = 0.0,
                avg_rms: float = 0.0, device_id: str | None = None,
                sequence: int | None = None, now_ms: int | None = None, extra: dict | None = None) -> str:
    """Status terbaru detector, dipublish (retained) untuk dashboard. extra: field opsional v2."""
    return json.dumps({
        **(extra or {}),
        "status": status,
        "reason": reason,
        "armed": armed,
        "run_minutes": run_minutes,
        "avg_rms": avg_rms,
        "device_id": device_id,
        "sequence": sequence,
        "at_ms": now_ms if now_ms is not None else int(time.time() * 1000),
    })


ALERT_KINDS = ("completed_after_spin", "stopped_without_spin", "correction", "sensor_lost")
ALERT_EVENTS = {"correction": "laundry_correction", "sensor_lost": "sensor_lost"}
LEGACY_ALERT_MAX_AGE_S = 900


def alert_json(run_minutes: float, reason: str, detected_at_ms: int, alert_id: str, kind: str,
               is_reminder: bool, valid_for_s: int) -> str:
    """Empat field pertama sama dengan alert lama, sehingga HP B lama tetap bekerja."""
    return json.dumps({
        "event": ALERT_EVENTS.get(kind, "laundry_done"), "run_minutes": run_minutes, "reason": reason,
        "detected_at_ms": detected_at_ms, "alert_id": alert_id, "kind": kind,
        "is_reminder": is_reminder, "valid_for_s": valid_for_s,
    })


def parse_alert(payload: str | bytes, now_ms: int) -> dict:
    """Validasi alert di HP B. ValueError jika rusak atau kedaluwarsa.

    Validasi tidak menghentikan alert palsu yang formatnya benar. Itu butuh broker berautentikasi.
    """
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("Alert harus berupa objek JSON")
    if not isinstance(value.get("event"), str) or not isinstance(value.get("reason"), str):
        raise ValueError("Field event atau reason tidak valid")
    minutes, detected = value.get("run_minutes"), value.get("detected_at_ms")
    if type(minutes) not in (int, float) or not math.isfinite(minutes) or minutes < 0:
        raise ValueError("run_minutes tidak valid")
    if type(detected) is not int or detected <= 0:
        raise ValueError("detected_at_ms tidak valid")
    valid_for = value.get("valid_for_s", LEGACY_ALERT_MAX_AGE_S)
    if type(valid_for) not in (int, float) or valid_for <= 0:
        raise ValueError("valid_for_s tidak valid")
    if now_ms - detected > valid_for * 1000:
        raise ValueError("Alert kedaluwarsa")
    return value
