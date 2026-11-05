"""Training, evaluasi, serialisasi, dengan data SINTETIS. Bukan bukti performa pada mesin cuci."""
import csv
import tempfile
import unittest
from pathlib import Path

try:
    import sklearn  # noqa: F401
except ImportError:
    raise unittest.SkipTest("scikit-learn belum terpasang (requirements-ml.txt)")

import numpy as np

from ml import evaluate as ev
from ml import metrics, replay, train
from ml.baselines.rule_activity import rule_activity
from ml.build_dataset import build
from ml.dataset_io import read_json, sha256_file
from ml.generate_synthetic import generate
from ml.split_dataset import group_of, make_split, read_windows, save_split
from nodes.detector_service.inference import ActivityModel
from shared.features import feature_names


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name)
        cls.sessions = cls.base / "synthetic"
        generate(cls.sessions, cycles=5, idle_sessions=2, time_scale=0.25, difficulty="hard")
        build(cls.sessions, "d", cls.base / "p", guard_s=5)
        cls.dataset = cls.base / "p" / "d"
        cls.split_path = save_split(make_split(cls.dataset, "v1"), cls.base / "m")
        cls.split = read_json(cls.split_path)
        cls.result = cls.train()

    @classmethod
    def train(cls, name="a", **kw):
        args = dict(grid="smoke", sessions_root=cls.sessions, make_figures=False, log=lambda *a: None)
        args.update(kw)
        return train.run(cls.dataset, cls.split_path, cls.base / name / "models", cls.base / name / "reports", **args)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()


class TrainingTests(Fixture):
    def test_baselines_and_candidates_present(self):
        names = {r["name"] for r in self.result["report"]["comparison"]}
        self.assertLessEqual({"baseline_mayoritas", "baseline_ambang", "baseline_fsm_lama"}, names)
        for algo in ("decision_tree", "logistic_regression", "random_forest"):
            for fset in ("F1", "F2", "F3"):
                self.assertIn(f"{algo}/{fset}", names)

    def test_threshold_baseline_is_not_labelled_as_ml(self):
        rows = {r["name"]: r for r in self.result["report"]["comparison"]}
        self.assertEqual(rows["baseline_ambang"]["kind"], "baseline")
        self.assertIsNone(rows["baseline_ambang"]["artifact_bytes"])

    def test_test_groups_excluded_from_training_rows(self):
        rows = train.load_dev_rows(self.dataset, self.split)
        self.assertFalse({group_of(r) for r in rows} & set(self.split["test"]))
        meta = self.result["metadata"]
        self.assertFalse(set(meta["train_groups"] + meta["validation_groups"]) & set(self.split["test"]))
        self.assertIsNone(meta["test_results"])

    def test_folds_are_group_aware(self):
        rows = train.load_dev_rows(self.dataset, self.split)
        groups = np.array([group_of(r) for r in rows])
        folds = train.group_folds(rows, self.split)
        self.assertGreaterEqual(len(folds), 2)
        for a, b in folds:
            self.assertFalse(set(groups[a]) & set(groups[b]))
            self.assertEqual(len(set(groups[b])), 1)

    def test_scaler_fitted_only_on_training_part(self):
        rows = train.load_dev_rows(self.dataset, self.split)
        names = feature_names("F2")
        X, y = train.matrix(rows, names), np.array([r["label"] for r in rows])
        a, b = train.group_folds(rows, self.split)[0]
        model = train.pipeline("logistic_regression", 1).fit(X[a], y[a])
        np.testing.assert_allclose(model.named_steps["scale"].mean_, X[a].mean(axis=0))
        self.assertFalse(np.allclose(model.named_steps["scale"].mean_, X.mean(axis=0)))

    def test_negative_control_near_chance(self):
        controls = self.result["report"]["controls"]
        self.assertLess(controls["shuffled_label_macro_f1"], 0.5)
        self.assertFalse(controls["shuffled_label_warning"])

    def test_invalid_values_rejected(self):
        rows = [{n: "1" for n in feature_names("F2")}]
        rows[0][feature_names("F2")[0]] = "nan"
        with self.assertRaises(train.TrainingError):
            train.matrix(rows, feature_names("F2"))
        with self.assertRaises(train.TrainingError):
            train.matrix([{}], feature_names("F2"))

    def test_mixed_dataset_rejected(self):
        self.assertEqual(train.classify_dataset([{"data_kind": "real"}, {"data_kind": "synthetic"}]), "MIXED")
        self.assertEqual(train.classify_dataset([{"data_kind": "real"}]), "REAL")
        self.assertEqual(train.classify_dataset([{"data_kind": "synthetic"}]), "SYNTHETIC")

    def test_identity_columns_not_features(self):
        names = self.result["metadata"]["feature_names"]
        self.assertFalse({"session_id", "machine_id", "cycle_id", "label", "window_end_ms"} & set(names))

    def test_reproducible_with_same_seed(self):
        a, b = self.train("r1", seed=7), self.train("r2", seed=7)
        pick = lambda r: [(c["name"], c["cv_macro_f1_per_fold"], c["params"]) for c in r["report"]["comparison"]]
        self.assertEqual(pick(a), pick(b))
        self.assertEqual(a["metadata"]["sha256"], b["metadata"]["sha256"])
        self.assertEqual(a["metadata"]["model_version"], b["metadata"]["model_version"])

    def test_experiment_recorded(self):
        with open(self.base / "a" / "reports" / "index.csv", newline="") as h:
            row = next(csv.DictReader(h))
        for key in ("experiment_id", "model_type", "dataset_id", "feature_schema_version", "split_version", "hyperparameters", "cv_macro_f1", "training_timestamp", "model_artifact"):
            self.assertTrue(row[key], key)
        self.assertTrue((self.result["experiment_dir"] / "comparison.csv").exists())

    def test_too_few_groups_refused(self):
        with self.assertRaises(train.TrainingError):
            train.group_folds([{"cycle_id": "C", "session_id": "s"}], {"cv_folds_leave_one_cycle_out": [], "validation": [], "train": ["C"]})


class SelectionTests(unittest.TestCase):
    def row(self, name, algo, fset, score, p95=1.0, kind="candidate"):
        return {"name": name, "kind": kind, "algorithm": algo, "feature_set": fset, "cv_macro_f1_mean": score, "timing": {"latency": {"p95_ms": p95}}}

    def test_clear_winner_selected(self):
        rows = [self.row("t", "decision_tree", "F2", 0.7), self.row("r", "random_forest", "F2", 0.9)]
        self.assertEqual(train.select_model(rows)["name"], "r")

    def test_simpler_model_wins_tie(self):
        rows = [self.row("t", "decision_tree", "F2", 0.895), self.row("r", "random_forest", "F2", 0.9)]
        self.assertEqual(train.select_model(rows)["name"], "t")

    def test_too_slow_model_excluded(self):
        rows = [self.row("t", "decision_tree", "F2", 0.5), self.row("r", "random_forest", "F2", 0.9, p95=500)]
        self.assertEqual(train.select_model(rows)["name"], "t")

    def test_baseline_never_selected(self):
        rows = [self.row("b", "baseline", "-", 1.0, kind="baseline"), self.row("t", "decision_tree", "F2", 0.2)]
        self.assertEqual(train.select_model(rows)["name"], "t")

    def test_threshold_rule(self):
        y = np.array(["IDLE", "IDLE", "SPIN", "SPIN"])
        P = np.array([[0.9, 0.05, 0.05], [0.4, 0.35, 0.25], [0.1, 0.8, 0.1], [0.45, 0.35, 0.2]])  # dua kesalahan lemah
        rule = np.array(["IDLE", "IDLE", "SPIN", "SPIN"])
        self.assertEqual(train.choose_threshold(y, P, rule)["threshold"], 0.5)


class MetricsTests(unittest.TestCase):
    def test_values_calculated_by_hand(self):
        y = ["IDLE", "IDLE", "WASHING", "WASHING", "SPIN", "SPIN"]
        p = ["IDLE", "WASHING", "WASHING", "WASHING", "SPIN", "IDLE"]
        m = metrics.compute_metrics(y, p)
        self.assertAlmostEqual(m["accuracy"], 4 / 6)
        self.assertAlmostEqual(m["per_class"]["IDLE"]["precision"], 0.5)
        self.assertAlmostEqual(m["per_class"]["WASHING"]["recall"], 1.0)
        self.assertAlmostEqual(m["per_class"]["WASHING"]["precision"], 2 / 3)
        self.assertAlmostEqual(m["per_class"]["SPIN"]["f1"], 2 / 3)
        self.assertAlmostEqual(m["macro_f1"], (0.5 + 0.8 + 2 / 3) / 3)
        self.assertEqual(m["confusion_matrix"]["rows_true_cols_pred"], [[1, 0, 1], [1, 1, 0], [0, 0, 2]])
        self.assertAlmostEqual(m["active_predicted_idle_rate"], 0.25)

    def test_majority_shows_why_accuracy_is_not_enough(self):
        y = ["IDLE"] * 90 + ["SPIN"] * 10
        m = metrics.compute_metrics(y, ["IDLE"] * 100)
        self.assertEqual(m["accuracy"], 0.9)
        self.assertLess(m["macro_f1"], 0.35)

    def test_calibration_error(self):
        self.assertAlmostEqual(metrics.expected_calibration_error([0.9, 0.9], [1, 0]), 0.4)
        self.assertAlmostEqual(metrics.expected_calibration_error([1.0, 1.0], [1, 1]), 0.0)

    def test_longest_false_idle(self):
        rows = [{"window_end_ms": t * 1000, "label": "WASHING"} for t in range(0, 50, 10)]
        self.assertEqual(metrics.longest_false_idle_seconds(rows, ["WASHING", "IDLE", "IDLE", "IDLE", "WASHING"]), 20.0)


class BaselineTests(unittest.TestCase):
    def test_rule_mapping(self):
        self.assertEqual(rule_activity(0.1, 0.0), "IDLE")
        self.assertEqual(rule_activity(0.3, 0.0), "WASHING")
        self.assertEqual(rule_activity(2.5, 0.0), "SPIN")
        self.assertEqual(rule_activity(0.3, 0.6), "SPIN")

    def test_legacy_rules_is_frozen_copy(self):
        digest = sha256_file(Path(__file__).resolve().parent.parent / "ml" / "baselines" / "legacy_rules.py")
        self.assertEqual(digest[:20], "d49d0601a63e078ff84f")

    def test_completion_metrics(self):
        self.assertEqual(replay.completion_metrics([50, 100, 130], 100), {"false_alerts": 1, "detected": True, "missed": False, "delay_s": 0.0})
        self.assertEqual(replay.completion_metrics([], 100)["missed"], True)
        self.assertEqual(replay.completion_metrics([50], 100)["false_alerts"], 1)

    def test_map_status_treats_done_as_idle(self):
        self.assertEqual([replay.map_status(s) for s in ("IDLE", "WASHING", "SPIN", "DONE", "DISARMED")], ["IDLE", "WASHING", "SPIN", "IDLE", "IDLE"])

    def test_true_bounds_and_pause_from_labels(self):
        labels = [{"label": "IDLE", "start_ms": 0, "end_ms": 10}, {"label": "WASHING", "start_ms": 10, "end_ms": 20},
                  {"label": "IDLE", "start_ms": 20, "end_ms": 30}, {"label": "SPIN", "start_ms": 30, "end_ms": 40}, {"label": "IDLE", "start_ms": 40, "end_ms": 90}]
        self.assertEqual(replay.true_cycle_bounds(labels), (10, 40))


class ReplayTests(Fixture):
    def test_replay_deterministic(self):
        folder = next(p for p in self.sessions.iterdir() if "C01" in p.name)
        self.assertEqual(replay.replay_legacy(folder), replay.replay_legacy(folder))

    def test_arms_replay_runs_through_production_rules(self):
        folder = next(p for p in self.sessions.iterdir() if "C01" in p.name)
        first = replay.replay_new(folder, "2_new_fsm_rule")
        self.assertEqual(first, replay.replay_new(folder, "2_new_fsm_rule"))
        self.assertEqual({s["source"] for s in first} - {"none"}, {"rule"})
        out = replay.evaluate_new_cycle(folder, "2_new_fsm_rule")
        for key in ("false_alerts", "detected", "missed", "delay_s", "corrections"):
            self.assertIn(key, out)
        with self.assertRaises(ValueError):
            replay.make_new_detector("x", None)

    def test_pause_analysis_ignores_idle_outside_cycle(self):
        folder = next(p for p in self.sessions.iterdir() if "C01" in p.name)
        out = replay.pause_analysis([folder])
        self.assertGreater(out["longest_pause_s"], 0)
        self.assertLess(out["longest_pause_s"], 60)   # jeda 2 menit x time_scale 0,25


class EvaluationTests(Fixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reports = cls.base / "a" / "reports"
        cls.report = ev.evaluate(cls.result["model_dir"], cls.base / "p", cls.sessions, cls.reports, make_figures=False)

    def test_results_and_synthetic_warning(self):
        self.assertIn("SINTETIS", self.report["warning"])
        for key in ("selected_model", "baseline_majority", "baseline_threshold", "baseline_fsm_old_mapped", "selected_with_rule_fallback"):
            self.assertIn("macro_f1", self.report["results"][key])
        self.assertEqual(self.report["results"]["selected_model"]["n"], self.report["n_test_windows"])
        self.assertTrue(self.report["end_to_end_arm1_legacy"])
        self.assertIn("Phase 6", self.report["end_to_end_pending"])

    def test_second_evaluation_refused_and_access_logged(self):
        with self.assertRaisesRegex(ev.EvaluationError, "sudah pernah"):
            ev.evaluate(self.result["model_dir"], self.base / "p", self.sessions, self.reports, make_figures=False)
        with open(self.reports / "test_access_log.csv", newline="") as h:
            self.assertEqual(len(list(csv.DictReader(h))), 1)

    def test_synthetic_never_claims_validation(self):
        claims = read_json(self.result["model_dir"] / "metadata.json")["status_claims"]
        self.assertFalse(claims["C_trained_on_real"])
        self.assertFalse(claims["D_validated_on_heldout_real"])
        self.assertFalse(claims["E_ready_for_production"])


class ArtifactTests(Fixture):
    def test_synthetic_marked_in_name_and_metadata(self):
        meta = self.result["metadata"]
        self.assertTrue(self.result["model_dir"].name.startswith("SYNTHETIC_"))
        self.assertEqual((meta["data_kind"], meta["dataset_type"], meta["production_allowed"]), ("synthetic", "SYNTHETIC", False))
        self.assertTrue(any("SINTETIS" in w for w in meta["warnings"]))

    def test_metadata_complete(self):
        for key in ("model_name", "model_version", "training_timestamp", "feature_schema_version", "feature_names", "classes", "label_mapping",
                    "hyperparameters", "data_kind", "dataset_id", "split_strategy", "validation_results", "test_results", "seed", "versions", "sha256",
                    "dataset_manifest_hash", "probability_threshold", "probability_calibrated"):
            self.assertIn(key, self.result["metadata"], key)
        self.assertIn("scikit_learn", self.result["metadata"]["versions"])
        self.assertIn("python", self.result["metadata"]["versions"])

    def test_round_trip_matches_training_path(self):
        rows = read_windows(self.dataset / "windows.csv")[:50]
        model = ActivityModel.load(self.result["model_dir"], allow_synthetic=True)
        import joblib
        raw = joblib.load(self.result["model_dir"] / "model.joblib")
        X = train.matrix(rows, model.feature_names)
        direct = raw.predict(X)
        through = [model.predict({n: float(r[n]) for n in model.feature_names}).activity for r in rows]
        self.assertEqual(list(direct), through)


if __name__ == "__main__":
    unittest.main()
