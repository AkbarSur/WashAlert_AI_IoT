"""Penyimpanan state siklus agar pulih setelah detector restart (FR pemulihan state). Tanpa MQTT."""

import json
import os
from pathlib import Path

MAX_AGE_MS = 6 * 3600 * 1000  # diusulkan: state lebih tua dari ini tidak lagi mewakili siklus berjalan


def save(path: str, body: dict, now_ms: int):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps({"saved_at_ms": now_ms, **body}), encoding="utf-8")
    os.replace(temporary, target)  # atomik: file lama tetap utuh jika proses mati saat menulis


def load(path: str, now_ms: int) -> dict | None:
    """None jika tidak ada atau terlalu tua. ValueError jika rusak."""
    target = Path(path)
    if not target.is_file():
        return None
    body = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(body, dict) or type(body.get("saved_at_ms")) is not int:
        raise ValueError("file state tidak valid")
    return body if now_ms - body["saved_at_ms"] <= MAX_AGE_MS else None
