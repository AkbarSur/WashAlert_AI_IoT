"""Pelabelan observasi tanpa menyentuh HP A (FR pelabelan observasi).

Langsung:  python -m ml.label_session --session S --observer A1
Dari video: python -m ml.label_session --session S --observer A1 --from-events events.csv
Waktu sinkron: python -m ml.label_session --session S --compute-offset

Tombol langsung: i=IDLE w=WASHING s=SPIN u=UNCERTAIN y=ketukan sinkron q=selesai.
"""

import argparse
import csv
import sys
import time
from pathlib import Path
from statistics import median

from ml.dataset_io import LABEL_COLUMNS, normalize_label, read_json, valid_code, write_json

KEYS = {"i": "IDLE", "w": "WASHING", "s": "SPIN", "u": "UNCERTAIN"}
SYNC_NOTE = "sync_tap"
SYNC_SECONDS = 15


class LabelWriter:
    """Satu interval aktif. Menekan label baru menutup interval sebelumnya."""

    def __init__(self, path: Path, session: str, observer: str, method: str):
        self.handle = open(path, "x", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.handle, fieldnames=LABEL_COLUMNS, lineterminator="\n")
        self.writer.writeheader()
        self.handle.flush()
        self.session, self.observer, self.method = session, observer, method
        self.current = None

    def mark(self, label: str, at_ms: int, note: str = ""):
        label = normalize_label(label)
        self.close_interval(at_ms)
        self.current = (at_ms, label, note)

    def close_interval(self, at_ms: int):
        if self.current is None:
            return
        start, label, note = self.current
        if at_ms <= start:
            raise ValueError("Waktu label harus naik")
        self.writer.writerow({"session_id": self.session, "start_ms": start, "end_ms": at_ms, "label": label,
                              "phase_note": note, "observer": self.observer, "method": self.method})
        self.handle.flush()
        self.current = None

    def close(self, at_ms: int):
        self.close_interval(at_ms)
        self.handle.close()


def run_interactive(writer: LabelWriter, read=input, clock=time.time, log=print):
    log("i=IDLE w=WASHING s=SPIN u=UNCERTAIN y=ketukan sinkron q=selesai. Tekan Enter setelah tombol.")
    while True:
        try:
            key = read("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            key = "q"
        now = int(clock() * 1000)
        if key == "q":
            writer.close(now)
            return
        if key == "y":
            writer.mark("UNCERTAIN", now, SYNC_NOTE)
            log("Ketukan sinkron dicatat: ketuk mesin tiga kali SEKARANG, lalu tandai kondisi mesin.")
        elif key in KEYS:
            writer.mark(KEYS[key], now)
            log(f"{KEYS[key]} sejak {now}")
        elif key:
            log("Tombol tidak dikenal")


def import_events(writer: LabelWriter, events_path: Path, video_start_ms: int):
    """events.csv: kolom video_s,label,phase_note. Baris terakhir label END menutup interval."""
    with open(events_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or rows[-1]["label"].strip().upper() != "END":
        raise ValueError("Baris terakhir events harus berlabel END")
    for row in rows[:-1]:
        writer.mark(row["label"], video_start_ms + int(float(row["video_s"]) * 1000), row.get("phase_note", "") or "")
    writer.close(video_start_ms + int(float(rows[-1]["video_s"]) * 1000))


def estimate_offset(rows: list[tuple[int, float]], sync_ms: int, search_s: float = 120) -> int | None:
    """Selisih jam HP A dikurangi jam pengamat, dari lonjakan ketukan pertama.

    rows: (t_epoch_ms HP A, |a|). None jika lonjakan tidak jelas, misalnya sampling
    terlalu jarang untuk menangkap ketukan.
    """
    near = [(t, m) for t, m in rows if abs(t - sync_ms) <= search_s * 1000]
    if len(near) < 5:
        return None
    center = median(m for _, m in near)
    mad = median(abs(m - center) for _, m in near)
    limit = center + max(0.5, 8 * mad)
    for t, m in near:
        if m >= limit:
            return t - sync_ms
    return None


def compute_offset(session_dir: Path) -> int | None:
    with open(session_dir / "labels.csv", newline="", encoding="utf-8") as handle:
        labels = list(csv.DictReader(handle))
    sync = [int(r["start_ms"]) for r in labels if r["phase_note"] == SYNC_NOTE]
    if not sync:
        raise ValueError("Tidak ada penanda sync_tap di labels.csv")
    rows = []
    with open(session_dir / "raw.csv", newline="", encoding="utf-8") as handle:
        for r in csv.DictReader(handle):
            try:
                rows.append((int(r["t_epoch_ms"]),
                             (float(r["ax"]) ** 2 + float(r["ay"]) ** 2 + float(r["az"]) ** 2) ** 0.5))
            except (TypeError, ValueError):
                continue
    offset = estimate_offset(rows, sync[0])
    if offset is not None:
        meta = read_json(session_dir / "meta.json")
        meta["clock_offset_ms"] = offset
        meta["clock_offset_method"] = "sync_tap"
        write_json(session_dir / "meta.json", meta)
    return offset


def main(argv=None):
    parser = argparse.ArgumentParser(description="Label observasi WashAlert AI")
    parser.add_argument("--session", required=True)
    parser.add_argument("--root", default="data/real")
    parser.add_argument("--observer")
    parser.add_argument("--method", choices=["direct", "video"], default="direct")
    parser.add_argument("--from-events", type=Path)
    parser.add_argument("--video-start-ms", type=int)
    parser.add_argument("--compute-offset", action="store_true")
    args = parser.parse_args(argv)
    session_dir = Path(args.root) / args.session
    try:
        if args.compute_offset:
            offset = compute_offset(session_dir)
            if offset is None:
                print("[LABEL] Ketukan tidak terdeteksi. Offset tidak diubah; catat di notes dan "
                      "andalkan zona transisi.")
                return 1
            print(f"[LABEL] clock_offset_ms = {offset}")
            return 0
        if not valid_code(args.observer):
            raise ValueError("--observer wajib, berupa kode tanpa spasi")
        session_dir.mkdir(parents=True, exist_ok=True)
        writer = LabelWriter(session_dir / "labels.csv", args.session, args.observer,
                             "video" if args.from_events else args.method)
        if args.from_events:
            if args.video_start_ms is None:
                raise ValueError("--from-events membutuhkan --video-start-ms")
            import_events(writer, args.from_events, args.video_start_ms)
        else:
            run_interactive(writer)
    except FileExistsError:
        print(f"[LABEL] Ditolak: {session_dir / 'labels.csv'} sudah ada dan tidak ditimpa", file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(f"[LABEL] Ditolak: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
