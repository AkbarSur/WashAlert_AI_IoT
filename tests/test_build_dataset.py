"""FR ekspor dataset, DML zona transisi, kesamaan jalur fitur."""
import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

from ml.build_dataset import DatasetError, build, edge_windows, label_at, main
from ml.dataset_io import read_json
from ml.validate_dataset import validate_session
from shared.features import ALL_FEATURE_COLUMNS, AggregateBuffer, compute_window_features, feature_names
from shared.processing import SensorSample
from tests.data_helpers import T0, make_session, read_raw, write_raw

IDENTITY = {"dataset_id", "session_id", "session_type", "cycle_id", "machine_id", "device_id", "data_kind", "label",
            "window_start_ms", "window_end_ms"}


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "synthetic"
        self.root.mkdir()
        self.out = self.base / "processed"

    def windows(self, dataset="d1"):
        with open(self.out / dataset / "windows.csv", newline="") as h:
            return list(csv.DictReader(h))

    def test_builds_labeled_windows_and_reports(self):
        make_session(self.root)
        q = build(self.root, "d1", self.out)
        rows = self.windows()
        self.assertEqual({r["label"] for r in rows}, {"IDLE", "WASHING", "SPIN"})
        self.assertEqual(q["windows"], len(rows))
        for name in ("manifest.json", "quality_report.json", "quality_report.md", "raw_labeled.csv"):
            self.assertTrue((self.out / "d1" / name).exists())
        self.assertIn("SINTETIS", (self.out / "d1" / "quality_report.md").read_text())

    def test_deterministic(self):
        make_session(self.root)
        build(self.root, "d1", self.out)
        build(self.root, "d1", self.base / "other")
        digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(digest(self.out / "d1" / "windows.csv"), digest(self.base / "other" / "d1" / "windows.csv"))
        self.assertEqual(digest(self.out / "d1" / "manifest.json"), digest(self.base / "other" / "d1" / "manifest.json"))

    def test_feature_columns_do_not_leak_label_or_identity(self):
        self.assertFalse(IDENTITY & set(ALL_FEATURE_COLUMNS))
        for name in ("F1", "F2", "F3"):
            self.assertFalse(IDENTITY & set(feature_names(name)))

    def test_windows_near_label_change_excluded(self):
        make_session(self.root, phases=(("IDLE", 120), ("WASHING", 120)))
        build(self.root, "d1", self.out, guard_s=10)
        change = T0 + 120_000
        for row in self.windows():
            start, end = int(row["window_start_ms"]), int(row["window_end_ms"])
            self.assertFalse(start - 10_000 < change < end + 10_000, row)

    def test_aggregate_only_from_single_label(self):
        make_session(self.root, phases=(("IDLE", 120), ("WASHING", 120)))
        q = build(self.root, "d1", self.out)
        self.assertGreater(q["drop_reasons"]["agregat_label_campur_atau_transisi"], 0)
        for row in self.windows():
            if row["label"] == "IDLE":
                self.assertLess(float(row["acc_dyn_rms_max"]), 0.1)
            else:
                self.assertGreater(float(row["acc_dyn_rms_mean"]), 0.3)

    def test_uncertain_never_reaches_training(self):
        make_session(self.root, phases=(("IDLE", 90), ("UNCERTAIN", 120), ("IDLE", 90)))
        q = build(self.root, "d1", self.out)
        self.assertNotIn("UNCERTAIN", {r["label"] for r in self.windows()})
        self.assertGreater(q["drop_reasons"]["agregat_uncertain_atau_tanpa_label"], 0)

    def test_clock_offset_shifts_labels(self):
        make_session(self.root, phases=(("IDLE", 120), ("WASHING", 120)), clock_offset_ms=60_000)
        build(self.root, "d1", self.out)
        for row in self.windows():
            if row["label"] == "IDLE":
                # IDLE berakhir di 180 dtk jam HP A, tetapi sinyal IDLE berakhir di 120 dtk.
                self.assertGreater(int(row["window_end_ms"]), T0 + 60_000)

    def test_gap_drops_affected_edge_window(self):
        folder = make_session(self.root, phases=(("IDLE", 120),))
        rows = read_raw(folder)
        for row in rows[102:]:
            row["t_mono_s"] = str(float(row["t_mono_s"]) + 60)
        write_raw(folder, rows)
        self.assertGreater(build(self.root, "d1", self.out)["drop_reasons"]["edge_gap"], 0)

    def test_incomplete_last_window_dropped(self):
        folder = make_session(self.root, phases=(("IDLE", 120),))
        write_raw(folder, read_raw(folder)[:-2])
        self.assertGreater(build(self.root, "d1", self.out)["drop_reasons"]["edge_sampel_kurang"], 0)

    def test_quarantined_row_breaks_window_not_pipeline(self):
        folder = make_session(self.root, phases=(("IDLE", 120),))
        rows = read_raw(folder)
        rows[7]["ax"] = "x"
        write_raw(folder, rows)
        q = build(self.root, "d1", self.out)
        self.assertEqual(q["rows_quarantined"], 1)
        self.assertTrue((self.out / "d1" / "quarantine.csv").exists())

    def test_stale_windows_excluded(self):
        folder = make_session(self.root, phases=(("IDLE", 120),))
        rows = read_raw(folder)
        for row in rows[:25]:
            row["gyro_fresh"] = "0"
            row["valid"] = "0"
        write_raw(folder, rows)
        self.assertGreater(build(self.root, "d1", self.out)["drop_reasons"]["edge_terlalu_banyak_stale"], 0)

    def test_extreme_sample_drops_window(self):
        folder = make_session(self.root, phases=(("IDLE", 120),))
        rows = read_raw(folder)
        rows[7]["ax"] = "500"
        write_raw(folder, rows)
        self.assertGreater(build(self.root, "d1", self.out)["drop_reasons"]["edge_sampel_tidak_valid"], 0)

    def test_rejected_session_reported_others_kept(self):
        make_session(self.root, session="sesi_ok")
        bad = make_session(self.root, session="sesi_buruk")
        (bad / "labels.csv").unlink()
        q = build(self.root, "d1", self.out)
        self.assertEqual((q["sessions_accepted"], q["sessions_rejected"]), (1, 1))
        self.assertEqual({r["session_id"] for r in self.windows()}, {"sesi_ok"})

    def test_empty_dataset_rejected(self):
        with self.assertRaisesRegex(DatasetError, "kosong"):
            build(self.root, "d1", self.out)
        self.assertEqual(main(["--root", str(self.root), "--dataset-id", "d2", "--out-root", str(self.out)]), 2)

    def test_session_shorter_than_aggregate_gives_empty_error(self):
        make_session(self.root, phases=(("IDLE", 10),))
        with self.assertRaisesRegex(DatasetError, "kosong"):
            build(self.root, "d1", self.out)

    def test_real_and_synthetic_cannot_mix(self):
        make_session(self.root, session="sesi_ok")
        make_session(self.root, session="sesi_nyata", kind="real")
        q = build(self.root, "d1", self.out)
        self.assertEqual(q["sessions_rejected"], 1)
        self.assertEqual({r["data_kind"] for r in self.windows()}, {"synthetic"})

    def test_root_must_declare_kind(self):
        other = self.base / "campur"
        other.mkdir()
        with self.assertRaises(DatasetError):
            build(other, "d1", self.out)

    def test_no_overwrite_without_flag(self):
        make_session(self.root)
        build(self.root, "d1", self.out)
        with self.assertRaisesRegex(DatasetError, "tidak ditimpa"):
            build(self.root, "d1", self.out)
        build(self.root, "d1", self.out, overwrite=True)

    def test_manifest_records_hashes_and_parameters(self):
        folder = make_session(self.root)
        build(self.root, "d1", self.out)
        manifest = read_json(self.out / "d1" / "manifest.json")
        self.assertEqual(manifest["window"]["aggregate_s"], 30.0)
        self.assertEqual(manifest["sessions"][0]["sha256"]["raw.csv"],
                         hashlib.sha256((folder / "raw.csv").read_bytes()).hexdigest())

    def test_raw_labeled_carries_metadata_and_uncertain_marker(self):
        make_session(self.root, phases=(("IDLE", 90), ("UNCERTAIN", 30)))
        build(self.root, "d1", self.out)
        with open(self.out / "d1" / "raw_labeled.csv", newline="") as h:
            rows = list(csv.DictReader(h))
        self.assertEqual(rows[0]["machine_id"], "M1")
        self.assertEqual(rows[0]["device_id"], "edge1")
        self.assertEqual({r["label"] for r in rows}, {"IDLE", "UNCERTAIN"})


class FeaturePathTests(unittest.TestCase):
    """Fitur dari file dataset harus sama dengan fitur jalur runtime (telemetri)."""

    def test_dataset_and_runtime_paths_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "synthetic"
            root.mkdir()
            folder = make_session(root, phases=(("WASHING", 180),))
            report = validate_session(folder, "synthetic")
            from collections import Counter
            dataset = list(edge_windows(report.rows, 5, report.median_dt, Counter()))
            rows = read_raw(folder)
            runtime = AggregateBuffer()
            file_buffer = AggregateBuffer()
            for i in range(len(rows) // 5):
                group = rows[i * 5:i * 5 + 5]
                samples = [SensorSample(float(r["t_mono_s"]), tuple(float(r[k]) for k in ("ax", "ay", "az")),
                                        tuple(float(r[k]) for k in ("gx", "gy", "gz"))) for r in group]
                live = compute_window_features(samples)
                start, end, stored = dataset[i]
                self.assertEqual(live, stored)
                runtime.add(end, live)
                file_buffer.add(end, stored)
                self.assertEqual(runtime.aggregate(), file_buffer.aggregate())
            self.assertIsNotNone(runtime.aggregate())


class LabelLookupTests(unittest.TestCase):
    def test_interval_is_half_open(self):
        labels = [{"start_ms": 10, "end_ms": 20, "label": "IDLE"}]
        self.assertEqual(label_at(labels, 0, 10), "IDLE")
        self.assertIsNone(label_at(labels, 0, 20))
        self.assertEqual(label_at(labels, 5, 24), "IDLE")


if __name__ == "__main__":
    unittest.main()
