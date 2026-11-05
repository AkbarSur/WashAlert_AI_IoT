"""Antarmuka inference untuk detector (FR pemuatan model, prediksi aktivitas).

Dipanggil detector melalui activity.py. FSM tidak mengakses model secara langsung.

Modul ini aman diimpor tanpa scikit-learn. Kegagalan muat menghasilkan ModelLoadError dengan
`reason` yang dapat ditampilkan sebagai fallback_reason. Masukan buruk tidak memicu exception:
`predict` mengembalikan ok=False beserta alasan, sehingga pemanggil dapat memakai aturan.
"""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from shared.features import ALL_FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION

METADATA_REQUIRED = ("model_name", "model_version", "feature_schema_version", "feature_names", "classes", "data_kind",
                     "sha256", "probability_threshold", "versions", "feature_ranges")
VALID_CLASSES = {"IDLE", "WASHING", "SPIN"}


class ModelLoadError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True)
class ActivityPrediction:
    ok: bool
    activity: str | None = None
    probabilities: dict = field(default_factory=dict)
    max_probability: float | None = None
    low_probability: bool = False
    out_of_range_features: tuple = ()
    model_version: str | None = None
    reason: str | None = None   # alasan ketika ok=False, atau catatan ketika perlu fallback

    @property
    def use_fallback(self) -> bool:
        """Saran untuk Phase 6: pakai aktivitas aturan pada jendela ini."""
        return (not self.ok) or self.low_probability or bool(self.out_of_range_features)


def _major_minor(version: str) -> tuple:
    return tuple(str(version).split(".")[:2])


class ActivityModel:
    """Model yang sudah diverifikasi. Buat lewat ActivityModel.load()."""

    def __init__(self, model, metadata: dict):
        self.model, self.metadata = model, metadata
        self.feature_names = tuple(metadata["feature_names"])
        self.classes = tuple(metadata["classes"])
        self.version = metadata["model_version"]
        self.threshold = float(metadata["probability_threshold"])
        self.data_kind = metadata["data_kind"]

    @staticmethod
    def load(model_dir, allow_synthetic: bool = False) -> "ActivityModel":
        model_dir = Path(model_dir)
        meta_path, model_path = model_dir / "metadata.json", model_dir / "model.joblib"
        if not model_path.is_file():
            raise ModelLoadError("model_missing", str(model_path))
        if not meta_path.is_file():
            raise ModelLoadError("metadata_missing", str(meta_path))
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ModelLoadError("metadata_invalid", str(exc)) from exc
        missing = [key for key in METADATA_REQUIRED if key not in metadata]
        if missing:
            raise ModelLoadError("metadata_invalid", f"field hilang: {missing}")
        if metadata["data_kind"] != "real" and not allow_synthetic:
            raise ModelLoadError("synthetic_not_allowed", "model dilatih dengan data sintetis")
        if metadata["feature_schema_version"] != FEATURE_SCHEMA_VERSION:
            raise ModelLoadError("feature_schema_mismatch",
                                 f"model {metadata['feature_schema_version']}, kode {FEATURE_SCHEMA_VERSION}")
        names = metadata["feature_names"]
        if not names or len(set(names)) != len(names) or not set(names) <= set(ALL_FEATURE_COLUMNS):
            raise ModelLoadError("feature_schema_mismatch", "feature_names tidak dikenal")
        if not set(metadata["classes"]) <= VALID_CLASSES or not metadata["classes"]:
            raise ModelLoadError("metadata_invalid", "classes tidak dikenal")
        # Hash diperiksa SEBELUM deserialisasi, karena joblib dapat menjalankan kode.
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        if digest != metadata["sha256"]:
            raise ModelLoadError("model_hash_mismatch", str(model_path))
        try:
            import joblib
            import numpy
            import sklearn
        except ImportError as exc:
            raise ModelLoadError("dependency_missing", str(exc)) from exc
        wanted = metadata["versions"].get("scikit_learn", "")
        if _major_minor(wanted) != _major_minor(sklearn.__version__):
            raise ModelLoadError("dependency_mismatch", f"model {wanted}, terpasang {sklearn.__version__}")
        try:
            model = joblib.load(model_path)
            actual = [str(c) for c in model.classes_]
            if actual != list(metadata["classes"]):
                raise ModelLoadError("metadata_invalid", f"classes model {actual}")
            model.predict_proba(numpy.zeros((1, len(names))))
        except ModelLoadError:
            raise
        except Exception as exc:  # file rusak dapat memicu berbagai exception
            raise ModelLoadError("model_invalid", str(exc)) from exc
        return ActivityModel(model, metadata)

    def predict(self, features: Mapping) -> ActivityPrediction:
        """features: dict fitur agregat. Fitur F3 lain yang tidak dipakai model diabaikan."""
        fail = lambda reason: ActivityPrediction(False, model_version=self.version, reason=reason)
        if not isinstance(features, Mapping):
            return fail("invalid_features")
        unknown = set(features) - set(ALL_FEATURE_COLUMNS)
        if unknown:
            return fail("unexpected_features")
        if any(name not in features for name in self.feature_names):
            return fail("missing_features")
        values = []
        for name in self.feature_names:
            value = features[name]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                return fail("invalid_features")
            values.append(float(value))
        import numpy
        try:
            proba = self.model.predict_proba(numpy.array([values]))[0]
        except Exception as exc:
            return fail(f"prediction_error: {exc}")
        probabilities = {c: round(float(p), 6) for c, p in zip(self.classes, proba)}
        activity = max(self.classes, key=lambda c: (probabilities[c], c))
        top = probabilities[activity]
        ranges = self.metadata["feature_ranges"]
        outside = tuple(n for n, v in zip(self.feature_names, values)
                        if not ranges[n]["low"] <= v <= ranges[n]["high"])
        low = top < self.threshold
        reason = "low_probability" if low else "out_of_training_range" if outside else None
        return ActivityPrediction(True, activity, probabilities, top, low, outside, self.version, reason)


def try_load(model_dir, allow_synthetic: bool = False) -> tuple:
    """Adapter Phase 6: (model, None) jika berhasil, (None, reason) jika perlu RULE_ONLY."""
    try:
        return ActivityModel.load(model_dir, allow_synthetic), None
    except ModelLoadError as exc:
        return None, exc.reason
