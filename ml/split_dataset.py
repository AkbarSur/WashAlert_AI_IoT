"""Pembagian train, validation, test berbasis siklus atau sesi (DML split, kunci test set).

python -m ml.split_dataset --dataset syn_v1 --version v1

Baris dari satu siklus atau sesi selalu berada pada satu bagian, sehingga jendela yang
tumpang tindih tidak dapat berpindah bagian. Modul ini tidak menghitung statistik apa pun:
scaler harus di-fit pada data training di Phase 5.
"""

import argparse
import csv
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from ml.dataset_io import TRAINING_LABELS, read_json, sha256_file, write_json

MIN_REAL_CYCLES = 8      # diusulkan (DML kecukupan data)
MIN_TEST_CYCLES = 2      # diusulkan
TEST_RATIO = 0.2
VAL_RATIO = 0.2
MAX_TRIES = 500


class SplitError(ValueError):
    pass


def read_windows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def group_of(row: dict) -> str:
    return row["cycle_id"] or row["session_id"]


def allocate(n: int) -> tuple[int, int]:
    """(jumlah test, jumlah validation) untuk n grup."""
    if n < 2:
        raise SplitError(f"Hanya {n} siklus. Minimal 2 agar train dan test terpisah")
    if n == 2:
        return 1, 0
    test = max(min(MIN_TEST_CYCLES, n - 2), round(n * TEST_RATIO))
    val = max(1, round(n * VAL_RATIO))
    while test + val > n - 1:
        val -= 1
    return test, val


def _labels(groups: list[str], per_group: dict) -> set:
    return set().union(*(per_group[g] for g in groups)) if groups else set()


def assign(cycles: list[str], per_group: dict, seed: int) -> tuple[dict, bool]:
    """Bagi siklus secara acak dengan seed, utamakan semua kelas ada di tiap bagian."""
    test_n, val_n = allocate(len(cycles))
    rng = random.Random(seed)
    order = sorted(cycles)
    best = None
    for _ in range(MAX_TRIES):
        rng.shuffle(order)
        parts = {"test": order[:test_n], "validation": order[test_n:test_n + val_n], "train": order[test_n + val_n:]}
        ok = all(set(TRAINING_LABELS) <= _labels(g, per_group) for g in parts.values() if g)
        best = best or {k: sorted(v) for k, v in parts.items()}
        if ok:
            return {k: sorted(v) for k, v in parts.items()}, True
    return best, False


def make_split(dataset_dir: Path, version: str, seed: int = 42, holdout_machine: str | None = None) -> dict:
    dataset_dir = Path(dataset_dir)
    manifest = read_json(dataset_dir / "manifest.json")
    if sha256_file(dataset_dir / "windows.csv") != manifest["windows_sha256"]:
        raise SplitError("windows.csv berubah sejak dibangun")
    rows = read_windows(dataset_dir / "windows.csv")
    if not rows:
        raise SplitError("Dataset kosong")
    kinds = {r["data_kind"] for r in rows}
    if len(kinds) != 1:
        raise SplitError(f"Data real dan sintetis tercampur: {kinds}")
    kind = kinds.pop()

    per_group = defaultdict(set)
    machine_of, type_of = {}, {}
    for r in rows:
        g = group_of(r)
        per_group[g].add(r["label"])
        machine_of.setdefault(g, set()).add(r["machine_id"])
        type_of[g] = r["session_type"]
    if any(len(m) > 1 for m in machine_of.values()):
        raise SplitError("Satu grup mencakup lebih dari satu mesin")

    machines = sorted({m for ms in machine_of.values() for m in ms})
    groups = sorted(per_group)
    holdout = []
    if holdout_machine:
        if holdout_machine not in machines:
            raise SplitError(f"Mesin {holdout_machine} tidak ada")
        if len(machines) < 2:
            raise SplitError("Hold-out mesin membutuhkan minimal 2 mesin")
        holdout = [g for g in groups if holdout_machine in machine_of[g]]
    rest = [g for g in groups if g not in holdout]
    cycles = [g for g in rest if type_of[g] == "cycle"]
    others = sorted(g for g in rest if type_of[g] != "cycle")

    warnings = []
    parts, covered = assign(cycles, per_group, seed)
    if holdout:
        parts["test"] = sorted(parts["test"] + holdout)
        warnings.append(f"Mesin {holdout_machine} seluruhnya di test untuk uji mesin yang belum dilihat")
    # Sesi non-siklus dibagi per sesi dengan rasio sama. Sedikit sesi: masuk train.
    rng = random.Random(seed + 1)
    shuffled = others[:]
    rng.shuffle(shuffled)
    n_test = round(len(shuffled) * TEST_RATIO)
    n_val = round(len(shuffled) * VAL_RATIO)
    parts["test"] = sorted(parts["test"] + shuffled[:n_test])
    parts["validation"] = sorted(parts["validation"] + shuffled[n_test:n_test + n_val])
    parts["train"] = sorted(parts["train"] + shuffled[n_test + n_val:])

    test_cycles = [g for g in parts["test"] if type_of[g] == "cycle"]
    if kind != "real":
        warnings.append("DATA SINTETIS: split ini hanya menguji perangkat lunak dan tidak boleh dipakai untuk klaim performa")
    if len(cycles) + len(holdout) < MIN_REAL_CYCLES:
        warnings.append(f"Hanya {len(cycles) + len(holdout)} siklus, di bawah target {MIN_REAL_CYCLES}. Evaluasi belum dapat diklaim memadai")
    if len(test_cycles) < MIN_TEST_CYCLES:
        warnings.append(f"Test hanya memiliki {len(test_cycles)} siklus, di bawah {MIN_TEST_CYCLES}")
    if not parts["validation"]:
        warnings.append("Tidak ada validation terpisah. Gunakan cross-validation per siklus")
    if not covered:
        warnings.append("Tidak semua bagian memiliki ketiga kelas")
    if len(machines) < 2:
        warnings.append("Hanya satu mesin. Klaim generalisasi antar-mesin tidak boleh dibuat")

    counts = {}
    where = {g: name for name, gs in parts.items() for g in gs}
    for name in parts:
        counts[name] = dict(Counter(r["label"] for r in rows if where[group_of(r)] == name))
    dev = sorted(g for g in parts["train"] + parts["validation"] if type_of[g] == "cycle")
    split = {
        "version": version, "dataset_id": manifest["dataset_id"], "data_kind": kind,
        "windows_sha256": manifest["windows_sha256"], "seed": seed,
        "group_rule": "cycle_id jika ada, selain itu session_id",
        "holdout_machine": holdout_machine,
        "train": parts["train"], "validation": parts["validation"], "test": parts["test"],
        "cv_folds_leave_one_cycle_out": [{"validation": [g], "train": [x for x in dev if x != g]} for g in dev] if len(dev) >= 2 else [],
        "n_windows_per_label": counts, "machines": machines,
        "evaluation_ready": kind == "real" and len(cycles) + len(holdout) >= MIN_REAL_CYCLES
                            and len(test_cycles) >= MIN_TEST_CYCLES and covered,
        "warnings": warnings,
        "rule": "Test dibuka sekali untuk evaluasi akhir. Scaler dan seleksi model hanya dari train dan validation.",
    }
    check_no_leakage(split)
    return split


def check_no_leakage(split: dict):
    seen = {}
    for name in ("train", "validation", "test"):
        for g in split[name]:
            if g in seen:
                raise SplitError(f"Kebocoran: {g} ada di {seen[g]} dan {name}")
            seen[g] = name


def verify_split(split: dict, dataset_dir: Path):
    """Periksa ulang hash dataset, grup, dan kebocoran pada tingkat baris."""
    check_no_leakage(split)
    dataset_dir = Path(dataset_dir)
    if sha256_file(dataset_dir / "windows.csv") != split["windows_sha256"]:
        raise SplitError("windows.csv berbeda dari saat split dikunci")
    where = {g: name for name in ("train", "validation", "test") for g in split[name]}
    for row in read_windows(dataset_dir / "windows.csv"):
        if group_of(row) not in where:
            raise SplitError(f"Grup {group_of(row)} tidak ada pada split")


def save_split(split: dict, manifests_dir: Path) -> Path:
    manifests_dir = Path(manifests_dir)
    manifests_dir.mkdir(parents=True, exist_ok=True)
    path = manifests_dir / f"split_{split['dataset_id']}_{split['version']}.json"
    if path.exists():
        raise SplitError(f"Split {path} sudah terkunci. Pakai versi baru dan catat alasannya")
    write_json(path, split)
    return path


def export_parts(split: dict, dataset_dir: Path, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = read_windows(Path(dataset_dir) / "windows.csv")
    where = {g: name for name in ("train", "validation", "test") for g in split[name]}
    columns = list(rows[0])
    counts = {}
    for name in ("train", "validation", "test"):
        part = [r for r in rows if where.get(group_of(r)) == name]
        counts[name] = len(part)
        with open(out_dir / f"{name}.csv", "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(part)
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description="Split dataset per siklus")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--processed-root", default="data/processed")
    parser.add_argument("--manifests", default="data/manifests")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--holdout-machine")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    dataset_dir = Path(args.processed_root) / args.dataset
    path = Path(args.manifests) / f"split_{args.dataset}_{args.version}.json"
    try:
        if args.verify:
            verify_split(read_json(path), dataset_dir)
            print(f"[SPLIT] {path} valid: tidak ada kebocoran grup, hash cocok")
            return 0
        split = make_split(dataset_dir, args.version, args.seed, args.holdout_machine)
        path = save_split(split, Path(args.manifests))
        counts = export_parts(split, dataset_dir, dataset_dir / "splits" / args.version)
    except (SplitError, OSError, KeyError) as exc:
        print(f"[SPLIT] Ditolak: {exc}", file=sys.stderr)
        return 2
    print(f"[SPLIT] {path}: {counts} jendela. evaluation_ready={split['evaluation_ready']}")
    for w in split["warnings"]:
        print(f"[SPLIT] PERINGATAN: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
