"""FR pemisahan data sintetis."""
import tempfile
import unittest
from pathlib import Path

from ml.dataset_io import read_json
from ml.generate_synthetic import PREFIX, generate
from ml.validate_dataset import validate_session
from tests.data_helpers import read_raw


class SyntheticTests(unittest.TestCase):
    def test_marked_and_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "synthetic"
            names = generate(root, cycles=2, idle_sessions=1, time_scale=0.1)
            self.assertEqual(len(names), 3)
            for name in names:
                self.assertTrue(name.startswith(PREFIX))
                folder = root / name
                self.assertTrue((folder / "SYNTHETIC_DATA_DO_NOT_REPORT_AS_REAL").exists())
                self.assertEqual(read_json(folder / "meta.json")["data_kind"], "synthetic")
                self.assertFalse(validate_session(folder, "synthetic").rejected)

    def test_refuses_other_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            for folder in ("real", "data"):
                with self.assertRaises(ValueError):
                    generate(Path(tmp) / folder, cycles=1, time_scale=0.1)
            self.assertFalse((Path(tmp) / "real").exists())

    def test_rejected_when_placed_in_real_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "synthetic"
            name = generate(root, cycles=1, idle_sessions=0, time_scale=0.1)[0]
            self.assertTrue(validate_session(root / name, "real").rejected)

    def test_reproducible_with_seed(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for tmp in (a, b):
                generate(Path(tmp) / "synthetic", cycles=1, idle_sessions=0, seed=5, time_scale=0.1)
            name = f"{PREFIX}SYNM1_C01"
            self.assertEqual(read_raw(Path(a) / "synthetic" / name), read_raw(Path(b) / "synthetic" / name))


if __name__ == "__main__":
    unittest.main()
