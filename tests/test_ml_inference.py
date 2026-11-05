"""Antarmuka inference: muat aman, validasi masukan, alasan fallback. Model kecil buatan, tanpa data nyata."""
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nodes.detector_service.inference import ActivityModel, ModelLoadError, try_load
from shared.features import ALL_FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION, feature_names

try:
    import joblib
    import numpy as np
    import sklearn
    from sklearn.pipeline import Pipeline
    from sklearn.tree import DecisionTreeClassifier
    HAS_SK = True
except ImportError:
    HAS_SK = False

NAMES = feature_names("F2")


def features(value=0.1):
    return {n: value for n in ALL_FEATURE_COLUMNS}


@unittest.skipUnless(HAS_SK, "scikit-learn belum terpasang")
class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "model"
        self.dir.mkdir()
        X = np.array([[0.0] * 12, [0.5] * 12, [3.0] * 12] * 5)
        y = np.array(["IDLE", "WASHING", "SPIN"] * 5)
        model = Pipeline([("clf", DecisionTreeClassifier(random_state=0))]).fit(X, y)
        joblib.dump(model, self.dir / "model.joblib")
        self.meta = {"model_name": "uji", "model_version": "uji-1", "feature_schema_version": FEATURE_SCHEMA_VERSION, "feature_names": list(NAMES),
                     "classes": [str(c) for c in model.classes_], "data_kind": "synthetic", "probability_threshold": 0.6,
                     "versions": {"scikit_learn": sklearn.__version__}, "feature_ranges": {n: {"low": 0.0, "high": 10.0} for n in NAMES},
                     "sha256": __import__("hashlib").sha256((self.dir / "model.joblib").read_bytes()).hexdigest()}
        self.write_meta()

    def write_meta(self):
        (self.dir / "metadata.json").write_text(json.dumps(self.meta))

    def load(self):
        return ActivityModel.load(self.dir, allow_synthetic=True)

    def assertReason(self, reason, **kw):
        with self.assertRaises(ModelLoadError) as ctx:
            ActivityModel.load(self.dir, **kw)
        self.assertEqual(ctx.exception.reason, reason)

    def test_prediction_output(self):
        p = self.load().predict(features(3.0))
        self.assertTrue(p.ok)
        self.assertEqual(p.activity, "SPIN")
        self.assertEqual(p.model_version, "uji-1")
        self.assertAlmostEqual(sum(p.probabilities.values()), 1.0, places=3)
        self.assertEqual(p.max_probability, p.probabilities["SPIN"])
        self.assertFalse(p.use_fallback)

    def test_feature_order_is_taken_from_metadata(self):
        shuffled = dict(reversed(list(features(0.5).items())))
        self.assertEqual(self.load().predict(shuffled).activity, "WASHING")

    def test_missing_feature_gives_reason(self):
        f = features()
        del f[NAMES[0]]
        p = self.load().predict(f)
        self.assertEqual((p.ok, p.reason), (False, "missing_features"))
        self.assertTrue(p.use_fallback)

    def test_unknown_extra_feature_rejected(self):
        self.assertEqual(self.load().predict({**features(), "session_id_hash": 1.0}).reason, "unexpected_features")

    def test_known_unused_features_ignored(self):
        self.assertTrue(self.load().predict(features()).ok)

    def test_invalid_values(self):
        model = self.load()
        for bad in (math.nan, math.inf, -1.0, "x", None, True):
            with self.subTest(bad=bad):
                self.assertEqual(model.predict({**features(), NAMES[0]: bad}).reason, "invalid_features")
        self.assertEqual(model.predict("bukan dict").reason, "invalid_features")

    def test_low_probability_flag(self):
        self.meta["probability_threshold"] = 1.01
        self.write_meta()
        p = self.load().predict(features())
        self.assertTrue(p.ok and p.low_probability and p.use_fallback)
        self.assertEqual(p.reason, "low_probability")

    def test_out_of_training_range_flag(self):
        p = self.load().predict(features(50.0))
        self.assertEqual(p.reason, "out_of_training_range")
        self.assertTrue(p.use_fallback)
        self.assertEqual(len(p.out_of_range_features), 12)

    def test_synthetic_refused_by_default(self):
        self.assertReason("synthetic_not_allowed")
        self.assertEqual(try_load(self.dir), (None, "synthetic_not_allowed"))
        self.assertIsNotNone(try_load(self.dir, allow_synthetic=True)[0])

    def test_model_missing(self):
        (self.dir / "model.joblib").unlink()
        self.assertReason("model_missing", allow_synthetic=True)

    def test_metadata_missing_or_broken(self):
        (self.dir / "metadata.json").write_text("{rusak")
        self.assertReason("metadata_invalid", allow_synthetic=True)
        (self.dir / "metadata.json").unlink()
        self.assertReason("metadata_missing", allow_synthetic=True)

    def test_metadata_field_missing(self):
        del self.meta["classes"]
        self.write_meta()
        self.assertReason("metadata_invalid", allow_synthetic=True)

    def test_tampered_file_not_deserialized(self):
        with open(self.dir / "model.joblib", "ab") as h:
            h.write(b"x")
        with mock.patch("joblib.load") as load:
            self.assertReason("model_hash_mismatch", allow_synthetic=True)
        load.assert_not_called()

    def test_corrupt_model_with_matching_hash(self):
        (self.dir / "model.joblib").write_bytes(b"bukan model")
        self.meta["sha256"] = __import__("hashlib").sha256(b"bukan model").hexdigest()
        self.write_meta()
        self.assertReason("model_invalid", allow_synthetic=True)

    def test_feature_schema_mismatch(self):
        self.meta["feature_schema_version"] = 99
        self.write_meta()
        self.assertReason("feature_schema_mismatch", allow_synthetic=True)
        self.meta["feature_schema_version"] = FEATURE_SCHEMA_VERSION
        self.meta["feature_names"] = ["session_id"]
        self.write_meta()
        self.assertReason("feature_schema_mismatch", allow_synthetic=True)

    def test_dependency_mismatch(self):
        self.meta["versions"]["scikit_learn"] = "0.1.0"
        self.write_meta()
        self.assertReason("dependency_mismatch", allow_synthetic=True)

    def test_label_mapping_mismatch(self):
        self.meta["classes"] = ["SPIN", "IDLE", "WASHING"]
        self.write_meta()
        self.assertReason("metadata_invalid", allow_synthetic=True)

    def test_done_is_not_accepted_as_class(self):
        self.meta["classes"] = ["IDLE", "DONE"]
        self.write_meta()
        self.assertReason("metadata_invalid", allow_synthetic=True)

    def test_untrained_model_rejected(self):
        joblib.dump(Pipeline([("clf", DecisionTreeClassifier())]), self.dir / "model.joblib")
        self.meta["sha256"] = __import__("hashlib").sha256((self.dir / "model.joblib").read_bytes()).hexdigest()
        self.write_meta()
        self.assertReason("model_invalid", allow_synthetic=True)

    def test_runtime_failure_returns_reason(self):
        model = self.load()
        with mock.patch.object(model.model, "predict_proba", side_effect=RuntimeError("rusak")):
            p = model.predict(features())
        self.assertFalse(p.ok)
        self.assertIn("prediction_error", p.reason)

    def test_missing_dependency_gives_reason(self):
        with mock.patch.dict(sys.modules, {"sklearn": None}):
            self.assertReason("dependency_missing", allow_synthetic=True)


class ImportTests(unittest.TestCase):
    def test_module_imports_without_ml_libraries(self):
        code = ("import sys\nfor m in ('sklearn','joblib','numpy'): sys.modules[m]=None\n"
                "from nodes.detector_service.inference import try_load\n"
                "print(try_load('tidak_ada'))")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
        self.assertIn("model_missing", out)

    def test_model_reaches_fsm_only_through_activity_module(self):
        # Pengganti test Phase 5 test_detector_still_does_not_use_model, yang sengaja berakhir pada integrasi Phase 6.
        root = Path(__file__).resolve().parent.parent / "nodes" / "detector_service"
        self.assertNotIn("detector_service.inference", (root / "main.py").read_text())
        self.assertNotIn("detector_service.inference", (root / "rules.py").read_text())
        self.assertIn("from nodes.detector_service.inference import try_load", (root / "activity.py").read_text())


if __name__ == "__main__":
    unittest.main()
