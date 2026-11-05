"""FR perekaman, identitas sesi, pencegahan tercampur, pelabelan. Sumber sensor tiruan."""
import csv
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ml import label_session as ls
from ml import measure_sampling as ms
from ml import record_session as rs
from ml.dataset_io import RAW_COLUMNS, normalize_label, read_json
from ml.validate_dataset import validate_session
from shared.processing import SensorSample
from tests.data_helpers import make_session


class FakeSource:
    def __init__(self, gyro_gaps=(), nan_at=None, stop_at=None, fault_at=None):
        self.i, self.gyro_gaps, self.nan_at, self.stop_at, self.fault_at = 0, set(gyro_gaps), nan_at, stop_at, fault_at
        self.sensor_fault = False

    def read(self):
        if self.i == self.stop_at:
            raise KeyboardInterrupt
        i = self.i
        self.i += 1
        self.sensor_fault = self.fault_at is not None and i >= self.fault_at
        value = float("nan") if i == self.nan_at else 0.1
        return SensorSample(10 + i * 0.5, (value, 0.0, 9.81), (0.01, 0.0, 0.0), True, i not in self.gyro_gaps)


def args(**kw):
    base = dict(session="sesi_uji", cycle_id=None, session_type="idle", source="simulator", device_id="edge1",
                phone_model="uji", machine_id="M1", machine_type="uji", program="-", placement="uji", orientation="uji",
                operator="A1", samples=5, interval=0.0, notes="")
    base.update(kw)
    return SimpleNamespace(**base)


class ClockedRecord(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "synthetic"
        self.now = 1_790_000_000.0

    def clock(self):
        self.now += 0.25
        return self.now

    def run_record(self, source=None, n=20, label=None, observer=None, session="sesi_uji", **kw):
        return rs.record(source or FakeSource(), self.root / session, rs.build_meta(args(session=session, **kw), "synthetic", source),
                         None, n, label, observer, sleep=lambda s: None, clock=self.clock, log=lambda *a: None)

    def rows(self, session="sesi_uji"):
        with open(self.root / session / "raw.csv", newline="") as h:
            return list(csv.DictReader(h))

    def test_writes_schema_and_counts(self):
        meta = self.run_record()
        rows = self.rows()
        self.assertEqual(len(rows), 20)
        self.assertEqual(tuple(rows[0]), RAW_COLUMNS)
        self.assertEqual(meta["status"], "complete")
        self.assertEqual(rows[0]["dt_s"], "")
        self.assertEqual(float(rows[1]["dt_s"]), 0.5)  # interval aktual, bukan nominal

    def test_missing_gyro_marked_invalid_and_not_zero_filled(self):
        self.run_record(FakeSource(gyro_gaps={3}))
        row = self.rows()[3]
        self.assertEqual((row["gyro_fresh"], row["valid"]), ("0", "0"))
        self.assertEqual(float(row["gx"]), 0.01)

    def test_nan_is_stored_as_invalid_not_replaced(self):
        self.run_record(FakeSource(nan_at=2))
        row = self.rows()[2]
        self.assertEqual(row["valid"], "0")
        self.assertEqual(row["ax"], "nan")

    def test_refuses_to_overwrite_session(self):
        self.run_record()
        digest = hashlib.sha256((self.root / "sesi_uji" / "raw.csv").read_bytes()).hexdigest()
        with self.assertRaises(rs.SessionError):
            self.run_record()
        self.assertEqual(digest, hashlib.sha256((self.root / "sesi_uji" / "raw.csv").read_bytes()).hexdigest())

    def test_interrupted_recording_keeps_data_and_status(self):
        meta = self.run_record(FakeSource(stop_at=7), n=None)
        self.assertEqual(meta["status"], "interrupted")
        self.assertEqual(len(self.rows()), 7)
        self.assertEqual(read_json(self.root / "sesi_uji" / "meta.json")["n_rows"], 7)

    def test_sensor_fault_recorded_in_metadata(self):
        self.assertTrue(self.run_record(FakeSource(fault_at=5))["sensor_fault_seen"])

    def test_whole_session_label_comes_from_observer_argument(self):
        self.run_record(label="idle", observer="A2")
        with open(self.root / "sesi_uji" / "labels.csv", newline="") as h:
            row = next(csv.DictReader(h))
        self.assertEqual((row["label"], row["observer"], row["method"]), ("IDLE", "A2", "direct"))

    def test_recorded_session_passes_validator(self):
        self.run_record(n=30, label="IDLE", observer="A1")
        report = validate_session(self.root / "sesi_uji", "synthetic")
        self.assertFalse(report.rejected, report.issues)


class ArgumentTests(unittest.TestCase):
    def check(self, **kw):
        base = dict(session="sesi_1", session_type="idle", cycle_id=None, machine_id="M1", device_id="edge1",
                    operator="A1", label=None, observer=None)
        base.update(kw)
        rs.check_args(**base)

    def test_valid_arguments(self):
        self.check()
        self.check(session_type="cycle", cycle_id="M1_C01")
        self.check(label="spin", observer="A1", session_type="segment")

    def test_invalid_arguments(self):
        cases = [dict(session="a b"), dict(session="../x"), dict(session_type="cycle"), dict(cycle_id="C1"),
                 dict(operator="Nama Lengkap"), dict(machine_id=""), dict(label="IDLE"), dict(label="DONE", observer="A"),
                 dict(label="X", observer="A"), dict(session_type="cycle", cycle_id="C1", label="IDLE", observer="A")]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.check(**case)

    def test_done_is_not_a_sensor_label(self):
        with self.assertRaisesRegex(ValueError, "FSM"):
            normalize_label("done")

    def test_simulator_cannot_write_to_real_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = rs.main(["--session", "sesi_x", "--session-type", "idle", "--machine-id", "M1", "--machine-type", "u",
                            "--phone-model", "u", "--placement", "u", "--orientation", "u", "--operator", "A1",
                            "--source", "simulator", "--root", str(Path(tmp) / "real"), "--max-samples", "2"])
            self.assertEqual(code, 2)
            self.assertFalse((Path(tmp) / "real" / "sesi_x").exists())

    def test_cli_with_simulator_marks_synthetic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "synthetic"
            code = rs.main(["--session", "sesi_x", "--session-type", "idle", "--machine-id", "M1", "--machine-type", "u",
                            "--phone-model", "u", "--placement", "u", "--orientation", "u", "--operator", "A1",
                            "--source", "simulator", "--root", str(root), "--max-samples", "6", "--interval", "0.001",
                            "--label", "uncertain", "--observer", "A1"])
            self.assertEqual(code, 0)
            self.assertEqual(read_json(root / "sesi_x" / "meta.json")["data_kind"], "synthetic")

    def test_recorder_does_not_need_mqtt_or_numpy(self):
        code = ("import sys, ml.record_session, ml.measure_sampling, ml.label_session, shared.features;"
                "assert not {'paho','numpy','sklearn'} & {m.split('.')[0] for m in sys.modules}")
        subprocess.run([sys.executable, "-c", code], check=True)


class LabelingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "labels.csv"

    def read(self):
        with open(self.path, newline="") as h:
            return list(csv.DictReader(h))

    def test_interactive_labels_close_previous_interval(self):
        keys = iter(["y", "i", "w", "z", "s", "q"])
        times = iter([100.0, 110.0, 200.0, 201.0, 300.0, 400.0])
        writer = ls.LabelWriter(self.path, "sesi_uji", "A1", "direct")
        ls.run_interactive(writer, read=lambda _: next(keys), clock=lambda: next(times), log=lambda *a: None)
        rows = self.read()
        self.assertEqual([r["label"] for r in rows], ["UNCERTAIN", "IDLE", "WASHING", "SPIN"])
        self.assertEqual(rows[0]["phase_note"], "sync_tap")
        self.assertEqual(rows[1]["end_ms"], rows[2]["start_ms"])
        self.assertEqual(rows[-1]["end_ms"], "400000")

    def test_labels_not_overwritten(self):
        ls.LabelWriter(self.path, "s", "A1", "direct").close(1)
        with self.assertRaises(FileExistsError):
            ls.LabelWriter(self.path, "s", "A1", "direct")

    def test_done_rejected_by_writer(self):
        writer = ls.LabelWriter(self.path, "s", "A1", "direct")
        with self.assertRaises(ValueError):
            writer.mark("DONE", 1)
        writer.close(2)

    def test_import_events_from_video(self):
        events = Path(self.tmp.name) / "events.csv"
        events.write_text("video_s,label,phase_note\n0,IDLE,\n10.5,WASHING,\n60,END,\n")
        writer = ls.LabelWriter(self.path, "s", "A1", "video")
        ls.import_events(writer, events, 1000)
        rows = self.read()
        self.assertEqual((rows[1]["start_ms"], rows[1]["end_ms"]), ("11500", "61000"))

    def test_events_must_end_with_end_row(self):
        events = Path(self.tmp.name) / "events.csv"
        events.write_text("video_s,label,phase_note\n0,IDLE,\n")
        writer = ls.LabelWriter(self.path, "s", "A1", "video")
        with self.assertRaises(ValueError):
            ls.import_events(writer, events, 1000)
        writer.close(1)

    def test_offset_from_tap_peak(self):
        rows = [(1000 + i * 500, 9.81) for i in range(100)]
        rows[40] = (rows[40][0], 15.0)
        self.assertEqual(ls.estimate_offset(rows, 20000), rows[40][0] - 20000)

    def test_offset_none_when_tap_not_captured(self):
        self.assertIsNone(ls.estimate_offset([(1000 + i * 500, 9.81) for i in range(100)], 20000))

    def test_compute_offset_updates_meta_only_when_found(self):
        folder = make_session(self.tmp.name, phases=(("IDLE", 60),))
        with open(folder / "labels.csv", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["phase_note"] = "sync_tap"
        with open(folder / "labels.csv", "w", newline="") as h:
            w = csv.DictWriter(h, fieldnames=list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        self.assertIsNone(ls.compute_offset(folder))
        self.assertEqual(read_json(folder / "meta.json")["clock_offset_ms"], 0)


class MeasureTests(unittest.TestCase):
    def test_summary_from_timestamps(self):
        samples = [SensorSample(i * 0.5, (0, 0, 9.91), (0, 0, 0), True, i != 1) for i in range(5)]
        out = ms.summarize(samples)
        self.assertEqual(out["rate_median_hz"], 2.0)
        self.assertEqual(out["gyro_empty_pct"], 20.0)
        self.assertAlmostEqual(out["rest_offset_mps2"], 0.1, places=3)
        self.assertIn("wajar", out["unit_check"])

    def test_unit_check_detects_g_and_bad_gyro(self):
        self.assertIn("g", ms.unit_check(1.0, 0.0))
        self.assertIn("gyro", ms.unit_check(9.8, 5.0))

    def test_needs_two_samples(self):
        with self.assertRaises(ValueError):
            ms.summarize([SensorSample(0, (0, 0, 9.8), (0, 0, 0))])

    def test_stream_probe_counts_objects(self):
        out = '{"a":{"values":[1,2,3]}}\n{"a":{"values":[1,2,3]}}'
        times = iter([0.0, 2.0])
        result = ms.probe_stream("a", 20, 2, run=lambda *a, **k: SimpleNamespace(stdout=out), clock=lambda: next(times))
        self.assertEqual((result["objects"], result["objects_per_s"]), (2, 1.0))


if __name__ == "__main__":
    unittest.main()
