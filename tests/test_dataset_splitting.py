"""DML split per siklus, kunci test set, kecukupan data, kebocoran."""
import csv
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from ml.build_dataset import build
from ml.dataset_io import read_json, write_json
from ml.generate_synthetic import generate
from ml.split_dataset import (SplitError, allocate, assign, check_no_leakage, export_parts, group_of, main, make_split,
                              read_windows, save_split, verify_split)


class SplitBase(unittest.TestCase):
    cycles = 8
    machines = 1

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.root = base / "synthetic"
        generate(cls.root, cycles=cls.cycles, idle_sessions=3, machines=cls.machines, time_scale=0.25)
        build(cls.root, "d1", base / "processed", guard_s=5)
        cls.dataset = base / "processed" / "d1"
        cls.base = base

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()


class SplitTests(SplitBase):
    def test_no_group_in_two_parts(self):
        split = make_split(self.dataset, "v1")
        check_no_leakage(split)
        where = {g: n for n in ("train", "validation", "test") for g in split[n]}
        found = {}
        for row in read_windows(self.dataset / "windows.csv"):
            found.setdefault(group_of(row), set()).add(where[group_of(row)])
        self.assertTrue(all(len(v) == 1 for v in found.values()))

    def test_session_time_ranges_of_parts_do_not_share_cycles(self):
        split = make_split(self.dataset, "v1")
        counts = export_parts(split, self.dataset, self.base / "parts")
        ids = {}
        for name in counts:
            ids[name] = {group_of(r) for r in read_windows(self.base / "parts" / f"{name}.csv")}
        self.assertFalse(ids["train"] & ids["test"])
        self.assertFalse(ids["train"] & ids["validation"])
        self.assertFalse(ids["validation"] & ids["test"])
        self.assertEqual(sum(counts.values()), len(read_windows(self.dataset / "windows.csv")))

    def test_row_level_split_would_be_detected(self):
        with self.assertRaisesRegex(SplitError, "Kebocoran"):
            check_no_leakage({"train": ["C1", "C2"], "validation": [], "test": ["C2"]})

    def test_deterministic_with_seed_and_changes_with_other_seed(self):
        self.assertEqual(make_split(self.dataset, "v1", 7), make_split(self.dataset, "v1", 7))
        tests = {tuple(make_split(self.dataset, "v1", s)["test"]) for s in range(5)}
        self.assertGreater(len(tests), 1)

    def test_all_classes_in_each_part_when_possible(self):
        split = make_split(self.dataset, "v1")
        for name in ("train", "validation", "test"):
            self.assertEqual(set(split["n_windows_per_label"][name]), {"IDLE", "WASHING", "SPIN"})

    def test_synthetic_never_marked_evaluation_ready(self):
        split = make_split(self.dataset, "v1")
        self.assertFalse(split["evaluation_ready"])
        self.assertTrue(any("SINTETIS" in w for w in split["warnings"]))

    def test_single_machine_warning(self):
        self.assertTrue(any("generalisasi" in w for w in make_split(self.dataset, "v1")["warnings"]))

    def test_cv_folds_leave_one_cycle_out_exclude_test(self):
        split = make_split(self.dataset, "v1")
        folds = split["cv_folds_leave_one_cycle_out"]
        self.assertEqual(len(folds), 6)
        for fold in folds:
            self.assertFalse(set(fold["validation"]) & set(fold["train"]))
            self.assertFalse(set(fold["validation"] + fold["train"]) & set(split["test"]))

    def test_locked_split_not_overwritten(self):
        split = make_split(self.dataset, "lock")
        save_split(split, self.base / "m")
        with self.assertRaisesRegex(SplitError, "terkunci"):
            save_split(split, self.base / "m")

    def test_verify_detects_changed_dataset(self):
        split = make_split(self.dataset, "v1")
        verify_split(split, self.dataset)
        with self.assertRaisesRegex(SplitError, "berbeda"):
            verify_split(dict(split, windows_sha256="0"), self.dataset)

    def test_no_preprocessing_is_fitted_in_split(self):
        before = (self.dataset / "windows.csv").read_bytes()
        split = make_split(self.dataset, "v1")
        self.assertEqual(before, (self.dataset / "windows.csv").read_bytes())
        self.assertFalse({"scaler", "mean", "std"} & set(split))

    def test_cli(self):
        args = ["--dataset", "d1", "--version", "cli", "--processed-root", str(self.base / "processed"),
                "--manifests", str(self.base / "cli")]
        self.assertEqual(main(args), 0)
        self.assertEqual(main(args), 2)
        self.assertEqual(main(args + ["--verify"]), 0)


class AllocationTests(unittest.TestCase):
    def test_table(self):
        for n, expected in {2: (1, 0), 3: (1, 1), 4: (2, 1), 8: (2, 2), 10: (2, 2), 20: (4, 4)}.items():
            self.assertEqual(allocate(n), expected, n)

    def test_one_cycle_rejected(self):
        with self.assertRaises(SplitError):
            allocate(1)

    def test_assign_reports_missing_class(self):
        labels = {"a": {"IDLE"}, "b": {"IDLE"}, "c": {"IDLE", "WASHING", "SPIN"}, "d": {"IDLE"}}
        self.assertFalse(assign(list(labels), labels, 1)[1])


class SmallDataTests(unittest.TestCase):
    def build(self, tmp, cycles, kind_real=False):
        base = Path(tmp)
        root = base / "synthetic"
        generate(root, cycles=cycles, idle_sessions=0, time_scale=0.25)
        build(root, "d", base / "p", guard_s=5)
        return base / "p" / "d"

    def test_few_cycles_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            split = make_split(self.build(tmp, 3), "v")
            self.assertTrue(any("di bawah target" in w for w in split["warnings"]))
            self.assertFalse(split["evaluation_ready"])

    def test_one_cycle_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SplitError):
                make_split(self.build(tmp, 1), "v")

    def test_real_data_with_enough_cycles_can_be_ready(self):
        """Hanya menguji logika bendera; kolom data_kind diubah pada salinan buatan."""
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self.build(tmp, 8)
            rows = read_windows(dataset / "windows.csv")
            for row in rows:
                row["data_kind"] = "real"
            with open(dataset / "windows.csv", "w", newline="") as h:
                w = csv.DictWriter(h, fieldnames=list(rows[0]), lineterminator="\n")
                w.writeheader()
                w.writerows(rows)
            from ml.dataset_io import sha256_file
            manifest = read_json(dataset / "manifest.json")
            manifest["windows_sha256"] = sha256_file(dataset / "windows.csv")
            write_json(dataset / "manifest.json", manifest)
            self.assertTrue(make_split(dataset, "v")["evaluation_ready"])

    def test_tampered_windows_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = self.build(tmp, 3)
            with open(dataset / "windows.csv", "a") as h:
                h.write("x\n")
            with self.assertRaisesRegex(SplitError, "berubah"):
                make_split(dataset, "v")


class MachineAwareTests(SplitBase):
    cycles = 9
    machines = 3

    def test_holdout_machine_only_in_test(self):
        split = make_split(self.dataset, "v", holdout_machine="SYNM2")
        rows = read_windows(self.dataset / "windows.csv")
        where = {g: n for n in ("train", "validation", "test") for g in split[n]}
        parts = {where[group_of(r)] for r in rows if r["machine_id"] == "SYNM2"}
        self.assertEqual(parts, {"test"})

    def test_unknown_machine_rejected(self):
        with self.assertRaises(SplitError):
            make_split(self.dataset, "v", holdout_machine="X")


if __name__ == "__main__":
    unittest.main()
