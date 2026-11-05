"""FR validator dan DML kualitas data: setiap aturan punya tindakan yang diuji."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from ml.dataset_io import write_json
from ml.validate_dataset import MARK_INVALID, QUARANTINE, REJECT, WARN, main, validate_session
from tests.data_helpers import make_session, read_raw, write_raw


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "synthetic"
        self.root.mkdir()

    def session(self, **kw):
        return make_session(self.root, **kw)

    def has(self, report, code, action):
        self.assertTrue(any(i.code == code and i.action == action for i in report.issues), report.issues)

    def test_valid_session_accepted(self):
        report = validate_session(self.session(), "synthetic")
        self.assertFalse(report.rejected, report.issues)
        self.assertGreater(len(report.rows), 100)

    def test_missing_files_rejected(self):
        folder = self.session()
        (folder / "labels.csv").unlink()
        self.has(validate_session(folder), "V07", REJECT)
        (folder / "meta.json").unlink()
        self.has(validate_session(folder), "V04", REJECT)
        (folder / "raw.csv").unlink()
        self.has(validate_session(folder), "V01", REJECT)

    def test_wrong_columns_rejected(self):
        folder = self.session()
        (folder / "raw.csv").write_text("a,b\n1,2\n")
        self.has(validate_session(folder), "V01", REJECT)

    def test_empty_raw_rejected(self):
        folder = self.session()
        write_raw(folder, [])
        self.has(validate_session(folder), "V16", REJECT)

    def test_too_few_rows_rejected(self):
        folder = self.session()
        write_raw(folder, read_raw(folder)[:5])
        self.has(validate_session(folder), "V16", REJECT)

    def test_single_bad_row_quarantined_not_imputed(self):
        for bad in ("", "abc", "nan", "inf"):
            with self.subTest(bad=bad):
                folder = self.session(session=f"sesi_{abs(hash(bad)) % 9999}")
                rows = read_raw(folder)
                rows[10]["ax"] = bad
                write_raw(folder, rows)
                report = validate_session(folder)
                self.has(report, "V02", QUARANTINE)
                self.assertFalse(report.rejected)
                self.assertNotIn(10, [r["seq"] for r in report.rows])

    def test_many_bad_rows_reject_session(self):
        folder = self.session()
        rows = read_raw(folder)
        for row in rows[:50]:
            row["gx"] = "x"
        write_raw(folder, rows)
        self.has(validate_session(folder), "V02", REJECT)

    def test_truncated_last_line_from_power_loss_is_quarantined(self):
        folder = self.session()
        with open(folder / "raw.csv", "a") as handle:
            handle.write("sesi_uji,9999,1")
        report = validate_session(folder)
        self.has(report, "V02", QUARANTINE)
        self.assertFalse(report.rejected)

    def test_duplicate_seq_quarantined(self):
        folder = self.session()
        rows = read_raw(folder)
        rows.insert(11, dict(rows[10]))
        write_raw(folder, rows)
        report = validate_session(folder)
        self.has(report, "V02", QUARANTINE)
        self.assertEqual(len(report.quarantined), 1)

    def test_out_of_order_rejected_not_sorted(self):
        folder = self.session()
        rows = read_raw(folder)
        rows[10], rows[11] = rows[11], rows[10]
        write_raw(folder, rows)
        self.has(validate_session(folder), "V03", REJECT)

    def test_monotonic_time_going_back_rejected(self):
        folder = self.session()
        rows = read_raw(folder)
        rows[20]["t_mono_s"] = "1.0"
        write_raw(folder, rows)
        self.has(validate_session(folder), "V03", REJECT)

    def test_invalid_epoch_rejected(self):
        folder = self.session()
        rows = read_raw(folder)
        rows[3]["t_epoch_ms"] = "-5"
        write_raw(folder, rows)
        self.has(validate_session(folder), "V03", REJECT)

    def test_epoch_clock_step_only_warns(self):
        folder = self.session()
        rows = read_raw(folder)
        rows[20]["t_epoch_ms"] = str(int(rows[19]["t_epoch_ms"]) - 100)
        write_raw(folder, rows)
        report = validate_session(folder)
        self.has(report, "V19", WARN)
        self.assertFalse(report.rejected)

    def test_all_identical_timestamps_rejected(self):
        folder = self.session()
        rows = read_raw(folder)
        for row in rows:
            row["t_mono_s"] = "5.0"
        write_raw(folder, rows)
        self.has(validate_session(folder), "V03", REJECT)

    def test_sampling_gap_warned(self):
        folder = self.session()
        rows = read_raw(folder)
        for row in rows[100:]:
            row["t_mono_s"] = str(float(row["t_mono_s"]) + 100)
        write_raw(folder, rows)
        self.has(validate_session(folder), "V09", WARN)

    def test_accel_in_g_rejected_not_converted(self):
        folder = self.session(gravity=1.0, phases=(("IDLE", 60),))
        self.has(validate_session(folder), "V14", REJECT)

    def test_declared_other_units_rejected(self):
        folder = self.session(units={"accel": "g", "gyro": "deg/s"})
        self.has(validate_session(folder), "V14", REJECT)

    def test_rest_offset_warned(self):
        folder = self.session(gravity=10.2 + 1.0, phases=(("IDLE", 60),))
        self.has(validate_session(folder), "V12", WARN)

    def test_extreme_magnitude_marked_invalid(self):
        folder = self.session()
        rows = read_raw(folder)
        rows[10]["ax"] = "500.0"
        write_raw(folder, rows)
        report = validate_session(folder)
        self.has(report, "V20", MARK_INVALID)
        self.assertEqual(report.n_invalid, 1)

    def test_stale_marked_invalid(self):
        folder = self.session()
        rows = read_raw(folder)
        rows[10]["gyro_fresh"] = "0"
        rows[10]["valid"] = "0"
        write_raw(folder, rows)
        self.has(validate_session(folder), "V10", MARK_INVALID)

    def test_frozen_axis_warned(self):
        folder = self.session()
        rows = read_raw(folder)
        for row in rows:
            row["gx"] = "0.123"
        write_raw(folder, rows)
        self.has(validate_session(folder), "V11", WARN)

    def edit_labels(self, folder, fn):
        with open(folder / "labels.csv", newline="") as handle:
            rows = list(csv.DictReader(handle))
        fn(rows)
        with open(folder / "labels.csv", "w", newline="") as h:
            w = csv.DictWriter(h, fieldnames=list(rows[0]) if rows else ["session_id"], lineterminator="\n")
            w.writeheader()
            w.writerows(rows)

    def test_unknown_label_rejected(self):
        for bad in ("DONE", "idle", "PAUSE"):
            with self.subTest(bad=bad):
                folder = self.session(session=f"sesi_{bad}")
                self.edit_labels(folder, lambda r: r[0].__setitem__("label", bad))
                self.has(validate_session(folder), "V07", REJECT)

    def test_overlapping_and_reversed_labels_rejected(self):
        folder = self.session()
        self.edit_labels(folder, lambda r: r[1].__setitem__("start_ms", str(int(r[0]["start_ms"]) + 1)))
        self.has(validate_session(folder), "V07", REJECT)
        folder = self.session(session="sesi_2")
        self.edit_labels(folder, lambda r: r[0].__setitem__("end_ms", r[0]["start_ms"]))
        self.has(validate_session(folder), "V07", REJECT)

    def test_labels_outside_recording_warned(self):
        folder = self.session()
        self.edit_labels(folder, lambda r: r.append(dict(r[-1], start_ms=str(int(r[-1]["end_ms"]) + 10**9),
                                                         end_ms=str(int(r[-1]["end_ms"]) + 10**9 + 5))))
        self.has(validate_session(folder), "V08", WARN)

    def test_cycle_without_spin_warned(self):
        self.has(validate_session(self.session(phases=(("IDLE", 60), ("WASHING", 60)))), "V13", WARN)

    def test_invalid_session_ids_rejected(self):
        folder = self.session(session="sesi_a")
        meta = json.loads((folder / "meta.json").read_text())
        meta["session_id"] = "sesi_b"
        write_json(folder / "meta.json", meta)
        self.has(validate_session(folder), "V05", REJECT)
        folder = self.session(session="sesi_c")
        rows = read_raw(folder)
        rows[5]["session_id"] = "lain"
        write_raw(folder, rows)
        self.has(validate_session(folder), "V05", REJECT)

    def test_kind_must_match_folder_and_source(self):
        self.has(validate_session(self.session(session="sesi_a"), "real"), "V06", REJECT)
        self.has(validate_session(self.session(session="sesi_b", kind="real", source="simulator")), "V06", REJECT)

    def test_full_name_in_metadata_rejected(self):
        self.has(validate_session(self.session(operator="Nama Lengkap")), "V04", REJECT)

    def test_corrupt_meta_rejected(self):
        folder = self.session()
        (folder / "meta.json").write_text("{rusak")
        self.has(validate_session(folder), "V04", REJECT)

    def test_interrupted_session_warned_and_usable(self):
        report = validate_session(self.session(status="interrupted"))
        self.has(report, "V18", WARN)
        self.assertFalse(report.rejected)

    def test_cli_exit_codes(self):
        self.session()
        self.assertEqual(main(["--root", str(self.root)]), 0)
        (self.root / "sesi_uji" / "meta.json").unlink()
        self.assertEqual(main(["--root", str(self.root)]), 1)
        self.assertEqual(main(["--root", str(Path(self.tmp.name) / "kosong")]), 2)


if __name__ == "__main__":
    unittest.main()
