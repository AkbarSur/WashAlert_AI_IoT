"""Pemeriksaan paket akhir: tautan dokumen, rahasia, path lokal, dan perintah pada README."""
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "synthetic", "processed", "experiments", "e2e", "soak"}


def text_files():
    for path in ROOT.rglob("*"):
        if path.is_file() and not SKIP_DIRS & set(path.relative_to(ROOT).parts) and path.suffix in {".py", ".md", ".js", ".html", ".css", ".yaml", ".txt", ".example", ".json"} and path.name != "mqtt.min.js":
            yield path


class Release(unittest.TestCase):
    def test_no_private_paths_or_credentials(self):
        pattern = re.compile(r"/home/claude|/root/|/tmp/claude|[A-Za-z0-9._%+-]+@gmail\.com|ghp_[A-Za-z0-9]{10}|BEGIN (RSA |EC )?PRIVATE KEY|MQTT_PASSWORD=\S")
        bad = [str(p.relative_to(ROOT)) for p in text_files() if p != Path(__file__).resolve() and pattern.search(p.read_text(encoding="utf-8", errors="replace"))]
        self.assertEqual(bad, [])

    def test_env_file_is_ignored_and_example_exists(self):
        ignore = (ROOT / ".gitignore").read_text()
        self.assertIn(".env", ignore)
        self.assertTrue((ROOT / ".env.example").is_file())

    def test_markdown_links_resolve(self):
        broken = []
        for doc in [ROOT / "README.md", *(ROOT / "docs").glob("*.md"), *(ROOT / "demo").glob("*.md")]:
            for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", doc.read_text(encoding="utf-8")):
                if not target.startswith(("http", "mailto")) and not (doc.parent / target).exists():
                    broken.append(f"{doc.name}: {target}")
        self.assertEqual(broken, [])

    def test_readme_modules_and_files_exist(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for module in set(re.findall(r"python -m ((?:ml|scripts)\.\w+)", readme)):
            self.assertTrue((ROOT / (module.replace(".", "/") + ".py")).is_file(), module)
        for script in set(re.findall(r"python (\w+\.py)", readme)):
            self.assertTrue((ROOT / script).is_file(), script)
        for number in range(1, 28):
            self.assertRegex(readme, rf"(?m)^## {number}\. ")

    def test_real_and_synthetic_data_stay_apart(self):
        self.assertEqual([p.name for p in (ROOT / "data/real").iterdir() if p.name != ".gitkeep"], [])
        for model in (ROOT / "models/development").iterdir():
            if model.is_dir():
                self.assertTrue(model.name.startswith("SYNTHETIC_"), model.name)
        self.assertEqual([p.name for p in (ROOT / "models/production").iterdir() if p.name != ".gitkeep"], [])

    def test_env_example_mode_is_safe_default(self):
        example = (ROOT / ".env.example").read_text()
        self.assertIn("DETECTION_MODE=RULE_ONLY", example)
        self.assertIn("ALLOW_SYNTHETIC_MODEL=false", example)


if __name__ == "__main__":
    unittest.main()
