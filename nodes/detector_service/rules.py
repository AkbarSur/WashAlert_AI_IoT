"""NODE 3: algoritma WashAlert (pure Python, tanpa MQTT).

Algoritma: finite state machine siklus mesin cuci.

    IDLE --(aktif >= start_s detik)--> WASHING <--> SPIN
      ^                                   |
      |                  (diam >= done_s, min_run_s terpenuhi)
      |                                   v
      +----(HP B digoyang = konfirmasi)-- DONE  (alert + pengingat berkala)

Aktivitas IDLE/WASHING/SPIN berasal dari sumber aktivitas (aturan atau model, lihat
activity.py). Semua keputusan siklus di file ini adalah aturan, bukan model.

Data processing di detector (melengkapi RMS & rotasi dari edge):
  C. Moving average RMS edge1 (n jendela terakhir) -> meredam lonjakan sesaat
  D. Timer durasi: lama getar/diam berturut-turut + total lama mesin bekerja
"""

from collections import deque
from dataclasses import dataclass
import os
import time

from nodes.detector_service.activity import UNKNOWN, RuleActivitySource
from shared.messages import Telemetry

IDLE, WASHING, SPIN, DONE = "IDLE", "WASHING", "SPIN", "DONE"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    start_s: float      # getar berturut-turut sebelum dianggap mulai mencuci
    done_s: float       # diam berturut-turut sebelum dianggap selesai
    remind_s: float     # jeda pengingat ulang kalau belum dikonfirmasi
    wash_threshold: float = 0.25    # m/s², RMS rata-rata = mesin bekerja
    still_threshold: float = 0.12   # m/s², di bawah ini = mesin diam (hysteresis)
    spin_threshold: float = 2.0     # m/s², getar keras = fase spin/peras
    spin_rotation: float = 0.5      # rad per jendela, goyangan khas spin
    ack_threshold: float = 3.0      # m/s², HP B digoyang sengaja
    # Nilai bawaan di bawah mempertahankan perilaku lama. from_env memakai nilai yang diusulkan.
    min_run_s: float = 0            # lama kerja minimum sebelum boleh DONE
    done_nospin_s: float | None = None  # batas diam jika belum ada spin; None sama dengan done_s
    ack_windows: int = 1            # jendela goyang berurutan untuk konfirmasi
    spin_windows: int = 3           # jendela rotasi tinggi berurutan untuk SPIN
    sensor_lost_s: float | None = None  # batas HP A hilang; None menonaktifkan watchdog
    abandon_s: float | None = None  # CR-006: siklus terlalu singkat yang diam selama ini kembali ke IDLE

    @staticmethod
    def from_env() -> "Config":
        real = os.getenv("CUCI_MODE", "demo").lower() == "real"
        start, done, remind = (60, 120, 300) if real else (6, 8, 20)
        done = _env_float("CUCI_DONE_S", done)
        nospin = _env_float("CUCI_DONE_NOSPIN_S", 2 * done if real else done)
        abandon = _env_float("CUCI_ABANDON_S", 0)  # CR-006 belum diputuskan, jadi nonaktif kecuali diisi
        return Config(
            start_s=_env_float("CUCI_START_S", start),
            done_s=done,
            remind_s=_env_float("CUCI_REMIND_S", remind),
            wash_threshold=_env_float("CUCI_WASH_TH", 0.25),
            still_threshold=_env_float("CUCI_STILL_TH", 0.12),
            spin_threshold=_env_float("CUCI_SPIN_TH", 2.0),
            spin_rotation=_env_float("CUCI_SPIN_ROT", 0.5),
            ack_threshold=_env_float("CUCI_ACK_TH", 3.0),
            min_run_s=_env_float("CUCI_MIN_RUN_S", 600 if real else 0),
            done_nospin_s=nospin,
            ack_windows=int(_env_float("CUCI_ACK_WINDOWS", 2)),
            spin_windows=int(_env_float("CUCI_SPIN_WINDOWS", 3)),
            sensor_lost_s=_env_float("CUCI_SENSOR_LOST_S", 60 if real else 20) or None,
            abandon_s=abandon or None,
        )


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str
    run_minutes: float = 0.0   # total lama mesin bekerja
    avg_rms: float = 0.0       # hasil moving average
    alert: bool = False        # True -> kirim notifikasi ke HP B
    publish: bool = True       # False -> jangan timpa status dashboard
    alert_kind: str | None = None   # completed_after_spin | stopped_without_spin | correction | sensor_lost
    is_reminder: bool = False
    clear_alert: bool = False       # True -> alert aktif berakhir
    activity: str | None = None
    activity_source: str | None = None
    probability: float | None = None
    source_reason: str | None = None
    classified_at_ms: int | None = None


class WasherDetector:
    def __init__(self, config: Config | None = None, window: int = 3, activity_source=None):
        self.cfg = config or Config.from_env()
        self.source = activity_source or RuleActivitySource(self.cfg)
        self.armed = True
        self.state = IDLE
        self.rms_window: deque[float] = deque(maxlen=window)
        self.latest: dict[str, Telemetry] = {}
        self.last_seq: dict[tuple[str, str], int] = {}
        self.rejected = {"stale": 0, "replay": 0}
        self.last_edge1_at: int | None = None
        self.sensor_lost = False
        self.estimate = None
        self._reset_cycle()

    # ---------- helper ----------
    def _reset_cycle(self):
        self.state = IDLE
        self.active_since: int | None = None
        self.still_since: int | None = None
        self.started_at: int | None = None
        self.finished_at: int | None = None
        self.last_alert_at: int | None = None
        self.spin_seen = False
        self.ack_count = 0
        self.alert_kind: str | None = None
        self.source.reset()

    # ---------- pemulihan setelah restart (FR pemulihan state) ----------
    def snapshot(self) -> dict:
        return {"armed": self.armed, "state": self.state, "started_at": self.started_at, "finished_at": self.finished_at,
                "last_alert_at": self.last_alert_at, "spin_seen": self.spin_seen, "alert_kind": self.alert_kind}

    def restore(self, saved: dict, now_ms: int):
        if saved["state"] not in (IDLE, WASHING, SPIN, DONE) or type(saved["armed"]) is not bool:
            raise ValueError("state tersimpan tidak valid")
        if saved["state"] != IDLE and type(saved["started_at"]) is not int:
            raise ValueError("started_at tersimpan tidak valid")
        self.armed = saved["armed"]
        self.state = saved["state"]
        self.started_at = saved["started_at"]
        self.finished_at = saved["finished_at"]
        self.last_alert_at = saved["last_alert_at"]
        self.spin_seen = bool(saved["spin_seen"])
        self.alert_kind = saved["alert_kind"]
        self.last_edge1_at = now_ms  # watchdog mulai dari saat pulih

    def set_armed(self, armed: bool):
        self.armed = armed
        if not armed:
            self._reset_cycle()
            self.rms_window.clear()
            self.sensor_lost = False

    def public_status(self) -> str:
        """Status untuk ditampilkan. SENSOR_LOST hanya saat siklus aktif (CR-004)."""
        if not self.armed:
            return "DISARMED"
        if self.sensor_lost and self.state in (WASHING, SPIN):
            return "SENSOR_LOST"
        return self.state

    def _run_minutes(self, now: int) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at is not None else now
        return round((end - self.started_at) / 60_000, 2)

    def _decision(self, now: int, reason: str, alert: bool = False, publish: bool = True, **extra) -> Decision:
        avg = sum(self.rms_window) / len(self.rms_window) if self.rms_window else 0.0
        e = self.estimate
        fields = {} if e is None else {"activity": e.activity, "activity_source": e.source, "probability": e.probability,
                                       "source_reason": e.reason, "classified_at_ms": e.classified_at_ms}
        return Decision(extra.pop("status", self.public_status()), reason, self._run_minutes(now), round(avg, 3), alert, publish, **fields, **extra)

    # ---------- entry point ----------
    def accept(self, data: Telemetry, now_ms: int | None = None) -> Decision:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        if abs(now - data.sent_at_ms) > 30_000:
            self.rejected["stale"] += 1
            return Decision("REJECTED_STALE", "Timestamp di luar jendela 30 detik", publish=False)
        key = (data.device_id, data.boot_id)
        if data.sequence <= self.last_seq.get(key, -1):
            self.rejected["replay"] += 1
            return Decision("REJECTED_REPLAY", "Sequence berulang/tidak urut", publish=False)
        self.last_seq[key] = data.sequence
        self.latest[data.device_id] = data
        if data.device_id == "edge1":
            self.last_edge1_at = now
            self.sensor_lost = False

        if not self.armed:
            return Decision("DISARMED", "Pemantauan dijeda pemilik")
        if data.device_id == "edge2":
            return self._owner_phone(data, now)
        return self._machine_phone(data, now)

    def tick(self, now_ms: int) -> Decision | None:
        """Dipanggil berkala oleh main.py. Menangani hal yang tidak boleh menunggu telemetri."""
        if not self.armed:
            return None
        cfg = self.cfg
        if cfg.sensor_lost_s and self.last_edge1_at is not None and not self.sensor_lost \
                and now_ms - self.last_edge1_at >= cfg.sensor_lost_s * 1000:
            self.sensor_lost = True
            self.active_since = None
            self.still_since = None   # waktu tanpa data bukan bukti mesin diam
            if self.state in (WASHING, SPIN):
                return self._decision(now_ms, "HP A tidak mengirim data saat siklus berjalan", alert=True, alert_kind="sensor_lost")
            return self._decision(now_ms, "HP A tidak mengirim data")
        if self.state == DONE:
            return self._maybe_remind(now_ms)
        return None

    def _maybe_remind(self, now: int) -> Decision | None:
        if now - (self.last_alert_at or now) >= self.cfg.remind_s * 1000:
            self.last_alert_at = now
            return self._decision(now, "Pengingat: cucian belum diambil", alert=True, alert_kind=self.alert_kind, is_reminder=True)
        return None

    # ---------- HP B (pemilik): konfirmasi dengan menggoyang HP ----------
    def _owner_phone(self, data: Telemetry, now: int) -> Decision:
        if self.state != DONE:
            self.ack_count = 0
            return self._decision(now, "Referensi HP pemilik diperbarui", publish=False)
        self.ack_count = self.ack_count + 1 if data.motion_rms >= self.cfg.ack_threshold else 0
        if self.ack_count >= self.cfg.ack_windows:
            minutes = self._run_minutes(now)
            self._reset_cycle()
            return Decision(IDLE, f"Pemilik konfirmasi cucian diambil (siklus {minutes} menit)", clear_alert=True)
        return self._decision(now, "Menunggu konfirmasi pemilik", publish=False)

    # ---------- HP A (di atas mesin): state machine ----------
    def _machine_phone(self, data: Telemetry, now: int) -> Decision:
        self.rms_window.append(data.motion_rms)                 # processing C
        avg = sum(self.rms_window) / len(self.rms_window)
        self.estimate = self.source.estimate(data, now, self.state, avg)
        return self.advance(self.estimate.activity, now)

    def advance(self, activity: str, now: int) -> Decision:
        """Satu-satunya tempat keputusan siklus. Sama untuk aktivitas dari aturan maupun model."""
        cfg = self.cfg
        if activity == UNKNOWN:
            # Tanpa data tepercaya, timer tidak boleh maju. Pengingat DONE tetap berjalan.
            self.active_since = None
            self.still_since = None
            reminder = self._maybe_remind(now) if self.state == DONE else None
            return reminder or self._decision(now, "Aktivitas tidak dapat ditentukan: timer ditahan")
        if self.state == IDLE:
            if activity != IDLE:
                self.active_since = self.active_since or now    # processing D
                if now - self.active_since >= cfg.start_s * 1000:
                    self.state = WASHING
                    self.started_at = self.active_since
                    self.active_since = None
                    return self._decision(now, "Getaran stabil terdeteksi: mesin mulai mencuci")
                return self._decision(now, "Ada getaran, menunggu cukup lama sebelum dianggap mencuci")
            self.active_since = None
            return self._decision(now, "Mesin diam")

        if self.state in (WASHING, SPIN):
            if activity == IDLE:
                self.still_since = self.still_since or now      # processing D
                still = now - self.still_since
                hold = cfg.done_s if self.spin_seen or cfg.done_nospin_s is None else cfg.done_nospin_s
                if self.still_since - self.started_at >= cfg.min_run_s * 1000:
                    if still >= hold * 1000:
                        self.state = DONE
                        self.finished_at = self.still_since
                        self.last_alert_at = now
                        self.alert_kind = "completed_after_spin" if self.spin_seen else "stopped_without_spin"
                        reason = ("Mesin berhenti bergetar: cucian selesai!" if self.spin_seen
                                  else "Mesin berhenti bergetar tanpa fase spin: kemungkinan cucian selesai")
                        return self._decision(now, f"{reason} (diam {still / 1000:.0f} dtk)", alert=True, alert_kind=self.alert_kind)
                elif cfg.abandon_s and still >= cfg.abandon_s * 1000:
                    self._reset_cycle()
                    return self._decision(now, "Getaran terlalu singkat untuk satu siklus: kembali ke IDLE tanpa alert")
                return self._decision(now, "Mesin jeda, memastikan apakah sudah selesai")
            self.still_since = None
            if activity == SPIN:
                self.spin_seen = True
            self.state = SPIN if activity == SPIN else WASHING
            return self._decision(now, "Getaran keras: fase peras (spin)" if activity == SPIN else "Mesin mencuci")

        # DONE: ingatkan ulang sampai pemilik konfirmasi, kecuali mesin ternyata aktif lagi
        if activity != IDLE:
            self.active_since = self.active_since or now
            if now - self.active_since >= cfg.start_s * 1000:
                self.state = WASHING
                self.finished_at = None
                self.still_since = None
                self.active_since = None
                self.last_alert_at = None
                self.ack_count = 0
                self.alert_kind = None
                return self._decision(now, "Koreksi: mesin aktif lagi setelah dinyatakan selesai", alert=True, alert_kind="correction", clear_alert=True)
        else:
            self.active_since = None
        return self._maybe_remind(now) or self._decision(now, "Cucian selesai, menunggu konfirmasi pemilik")
