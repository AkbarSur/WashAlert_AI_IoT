"""Satu-satunya definisi fitur WashAlert AI (FR-010, FR-005, NFR definisi fitur tunggal).

Dipakai oleh edge, pembuatan dataset, dan nanti inference. Hanya memakai pustaka
standar agar berjalan di Termux tanpa NumPy. Rumus ada di docs/feature_engineering.md.

Jendela edge      : N sampel berurutan tanpa tumpang tindih, menjadi satu telemetri.
Jendela agregat   : jendela edge dalam `aggregate_s` terakhir. Hanya memakai masa lalu.
"""

from collections import deque
from dataclasses import dataclass
from math import isfinite, sqrt
from statistics import fmean, median, pstdev, pvariance

from shared.processing import SensorSample, extract_features

FEATURE_SCHEMA_VERSION = 1
TELEMETRY_SCHEMA_VERSION = 2

BASE_F1 = ("motion_rms", "rotation_rad")
BASE_F2 = ("acc_dyn_rms", "acc_mag_ptp", "gyro_rms", "gyro_max")
QUALITY_FIELDS = ("window_s", "n_samples", "actual_hz", "stale_count")
STATS = ("mean", "std", "max")
FEATURE_SETS = {"F1": BASE_F1, "F2": BASE_F2, "F3": BASE_F1 + BASE_F2}

MIN_FRESH_RATIO = 0.6  # diusulkan, perlu validasi (V10)


class InvalidWindow(ValueError):
    """Jendela tidak dapat dihitung: sampel kurang atau nilainya tidak finite."""


def feature_names(feature_set: str = "F2") -> tuple[str, ...]:
    """Urutan kolom fitur model. Urutan ini disimpan di metadata model pada Phase 5."""
    return tuple(f"{base}_{stat}" for base in FEATURE_SETS[feature_set] for stat in STATS)


ALL_FEATURE_COLUMNS = feature_names("F3")


def compute_window_features(samples: list[SensorSample]) -> dict:
    """Fitur satu jendela edge. Deterministik: input sama menghasilkan output sama."""
    if len(samples) < 2:
        raise InvalidWindow("Minimal 2 sampel")
    for sample in samples:
        if not all(isfinite(v) for v in (*sample.acceleration, *sample.gyroscope, sample.seconds)):
            raise InvalidWindow("Nilai sensor atau timestamp tidak finite")

    legacy = extract_features(samples)  # processing A dan B lama, maknanya tidak berubah
    axes = list(zip(*(s.acceleration for s in samples)))
    magnitudes = [sqrt(sum(v * v for v in s.acceleration)) for s in samples]
    omegas = [sqrt(sum(v * v for v in s.gyroscope)) for s in samples]
    window_s = max(0.0, samples[-1].seconds - samples[0].seconds)
    n = len(samples)
    return {
        "motion_rms": legacy.motion_rms,
        "rotation_rad": legacy.rotation_rad,
        "acc_dyn_rms": round(sqrt(sum(pvariance(axis) for axis in axes)), 6),
        "acc_mag_ptp": round(max(magnitudes) - min(magnitudes), 6),
        "gyro_rms": round(sqrt(sum(w * w for w in omegas) / n), 6),
        "gyro_max": round(max(omegas), 6),
        "window_s": round(window_s, 6),
        "n_samples": n,
        "actual_hz": round((n - 1) / window_s, 4) if window_s > 0 else 0.0,
        "stale_count": sum(1 for s in samples if not (s.accel_fresh and s.gyro_fresh)),
    }


def telemetry_extra(window: dict, sensor_fault: bool = False) -> dict:
    """Field opsional telemetri v2 (SRS 5.7)."""
    extra = {"schema_version": TELEMETRY_SCHEMA_VERSION, "sensor_fault": bool(sensor_fault)}
    for key in QUALITY_FIELDS + BASE_F2:
        extra[key] = window[key]
    return extra


def window_usable(window: dict) -> bool:
    """Jendela edge boleh masuk jendela agregat, saat training maupun inference."""
    n = window["n_samples"]
    return n >= 2 and window["window_s"] > 0 and (n - window["stale_count"]) / n >= MIN_FRESH_RATIO


@dataclass(frozen=True)
class WindowConfig:
    """Nilai awal diusulkan (DML jendela agregat). Final setelah gerbang G1."""
    aggregate_s: float = 30.0
    min_windows: int = 3
    min_coverage_s: float = 20.0


class AggregateBuffer:
    """Jendela agregat bergeser. Hanya memakai jendela yang sudah berakhir."""

    def __init__(self, config: WindowConfig | None = None):
        self.config = config or WindowConfig()
        self.items: deque[tuple[int, dict]] = deque()

    def add(self, end_ms: int, window: dict) -> bool:
        """False jika jendela ditolak: tidak layak, atau waktunya mundur."""
        if self.items and end_ms <= self.items[-1][0]:
            return False
        if not window_usable(window):
            self._prune(end_ms)
            return False
        self.items.append((end_ms, window))
        self._prune(end_ms)
        return True

    def _prune(self, now_ms: int):
        limit = now_ms - self.config.aggregate_s * 1000
        while self.items and self.items[0][0] <= limit:
            self.items.popleft()

    def coverage_s(self) -> float:
        if not self.items:
            return 0.0
        first_end, first = self.items[0]
        return (self.items[-1][0] - first_end) / 1000 + first["window_s"]

    def ready(self) -> bool:
        return (len(self.items) >= self.config.min_windows
                and self.coverage_s() >= self.config.min_coverage_s)

    def aggregate(self) -> dict | None:
        """Statistik semua fitur (F3), atau None jika data belum cukup."""
        if not self.ready():
            return None
        windows = [w for _, w in self.items]
        out = {}
        for base in FEATURE_SETS["F3"]:
            values = [w[base] for w in windows]
            out[f"{base}_mean"] = round(fmean(values), 6)
            out[f"{base}_std"] = round(pstdev(values), 6)
            out[f"{base}_max"] = round(max(values), 6)
        return out

    def quality(self) -> dict:
        windows = [w for _, w in self.items]
        total = sum(w["n_samples"] for w in windows)
        first_end, first = self.items[0]
        return {
            "window_start_ms": int(first_end - first["window_s"] * 1000),
            "window_end_ms": self.items[-1][0],
            "n_edge_windows": len(windows),
            "coverage_s": round(self.coverage_s(), 3),
            "median_hz": round(median(w["actual_hz"] for w in windows), 4),
            "stale_ratio": round(sum(w["stale_count"] for w in windows) / total, 4),
        }
