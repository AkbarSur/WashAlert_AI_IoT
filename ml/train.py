"""Training model aktivitas (FR perintah training, DML baseline, kandidat, split).

python -m ml.train --dataset real_v1 --split v1

Test set tidak dibaca di sini. Baris test dibuang sebelum matriks fitur dibuat.
Evaluasi akhir dilakukan terpisah oleh ml.evaluate.
"""

import argparse
import csv
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.base import clone
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, make_scorer
from sklearn.model_selection import GridSearchCV, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from ml import figures, replay
from ml.baselines.rule_activity import rule_activity
from ml.dataset_io import read_json, sha256_file, write_json
from ml.metrics import CLASSES, compute_metrics, expected_calibration_error
from ml.split_dataset import check_no_leakage, group_of, read_windows, verify_split
from shared.features import FEATURE_SCHEMA_VERSION, feature_names

MODEL_NAME = "washalert_activity"
SIMPLICITY = {"decision_tree": 0, "logistic_regression": 1, "svm_rbf": 2, "random_forest": 3}
FEATURE_PREFERENCE = {"F2": 0, "F1": 1, "F3": 2}   # F2 tanpa offset dan tidak bergantung durasi jendela
TIE_MARGIN = 0.01            # diusulkan, ditetapkan sebelum melihat test
MAX_LATENCY_P95_MS = 100.0   # NFR latensi inference, diusulkan
THRESHOLD_GRID = (0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
NOTES = {
    "decision_tree": ("Aturan dapat dicetak, sangat ringan", "Mudah overfit, batas keputusan kasar"),
    "logistic_regression": ("Ringan, koefisien dapat dibaca", "Batas linear, perlu scaling"),
    "random_forest": ("Menangkap interaksi fitur, tidak perlu scaling", "Artefak dan latensi lebih besar, sulit dijelaskan per keputusan"),
    "svm_rbf": ("Batas non-linear", "Lambat pada data besar, probabilitas mahal"),
}


class TrainingError(ValueError):
    pass


def pipeline(algo: str, seed: int) -> Pipeline:
    if algo == "decision_tree":
        return Pipeline([("clf", DecisionTreeClassifier(class_weight="balanced", random_state=seed))])
    if algo == "random_forest":
        return Pipeline([("clf", RandomForestClassifier(class_weight="balanced", random_state=seed, n_jobs=1))])
    if algo == "logistic_regression":
        return Pipeline([("scale", StandardScaler()), ("clf", LogisticRegression(class_weight="balanced", max_iter=2000, random_state=seed))])
    if algo == "svm_rbf":
        return Pipeline([("scale", StandardScaler()), ("clf", SVC(class_weight="balanced", probability=True, random_state=seed))])
    raise TrainingError(f"Algoritma tidak dikenal: {algo}")


GRIDS = {
    "full": {
        "decision_tree": {"clf__max_depth": [3, 5, 8], "clf__min_samples_leaf": [1, 5, 20]},
        "logistic_regression": {"clf__C": [0.1, 1.0, 10.0]},
        "random_forest": {"clf__n_estimators": [100], "clf__max_depth": [5, 8, None], "clf__min_samples_leaf": [1, 5], "clf__max_features": ["sqrt"]},
        "svm_rbf": {"clf__C": [1.0, 10.0]},
    },
    "smoke": {
        "decision_tree": {"clf__max_depth": [3, 5]},
        "logistic_regression": {"clf__C": [1.0]},
        "random_forest": {"clf__n_estimators": [10], "clf__max_depth": [5]},
        "svm_rbf": {"clf__C": [1.0]},
    },
}


def classify_dataset(rows: list[dict]) -> str:
    kinds = {r["data_kind"] for r in rows}
    return {frozenset({"real"}): "REAL", frozenset({"synthetic"}): "SYNTHETIC"}.get(frozenset(kinds), "MIXED")


def load_dev_rows(dataset_dir: Path, split: dict) -> list[dict]:
    """Hanya baris train dan validation. Grup test dibuang di sini."""
    verify_split(split, dataset_dir)
    rows = read_windows(dataset_dir / "windows.csv")
    kind = classify_dataset(rows)
    if kind == "MIXED":
        raise TrainingError("Dataset MIXED ditolak: data nyata dan sintetis tidak boleh dilatih bersama")
    dev = set(split["train"]) | set(split["validation"])
    keep = [r for r in rows if group_of(r) in dev]
    if not keep:
        raise TrainingError("Tidak ada data pengembangan")
    labels = {r["label"] for r in keep}
    if not labels <= set(CLASSES):
        raise TrainingError(f"Label tidak dikenal: {labels - set(CLASSES)}")
    if len(labels) < 2:
        raise TrainingError("Data pengembangan hanya memiliki satu kelas")
    return keep


def matrix(rows: list[dict], names) -> np.ndarray:
    try:
        X = np.array([[float(r[n]) for n in names] for r in rows], dtype=float)
    except (KeyError, ValueError) as exc:
        raise TrainingError(f"Kolom fitur tidak valid: {exc}") from exc
    if not np.isfinite(X).all():
        raise TrainingError("Fitur berisi NaN atau Infinity")
    return X


def group_folds(rows: list[dict], split: dict) -> list[tuple]:
    """Leave-one-cycle-out. Sesi non-siklus selalu di training, dan tidak pernah divalidasi."""
    groups = np.array([group_of(r) for r in rows])
    folds = []
    cycles = {g for f in split["cv_folds_leave_one_cycle_out"] for g in f["validation"]}
    for fold in split["cv_folds_leave_one_cycle_out"]:
        val = fold["validation"]
        val_idx = np.where(np.isin(groups, val))[0]
        train_idx = np.where(~np.isin(groups, list(cycles)) | np.isin(groups, fold["train"]))[0]
        if len(val_idx) and len(train_idx):
            folds.append((train_idx, val_idx))
    if not folds and split["validation"] and split["train"]:
        folds = [(np.where(np.isin(groups, split["train"]))[0], np.where(np.isin(groups, split["validation"]))[0])]
    if not folds:
        raise TrainingError("Tidak cukup grup untuk validasi. Minimal 2 siklus pada data pengembangan")
    for train_idx, val_idx in folds:
        if set(groups[train_idx]) & set(groups[val_idx]):
            raise TrainingError("Kebocoran: grup sama pada train dan validation")
    return folds


def validated_rows(folds) -> np.ndarray:
    """Baris yang pernah menjadi validation. Sesi non-siklus selalu training, sehingga tidak termasuk."""
    return np.unique(np.concatenate([v for _, v in folds]))


def fold_scores(folds, y, preds_by_fold) -> list[float]:
    return [float(f1_score(y[v], p, labels=list(CLASSES), average="macro", zero_division=0)) for (_, v), p in zip(folds, preds_by_fold)]


def oof_predict(model, X, y, folds, proba=False):
    pred = np.empty(len(y), dtype=object)
    P = np.zeros((len(y), len(CLASSES)))
    by_fold = []
    for train_idx, val_idx in folds:
        m = clone(model).fit(X[train_idx], y[train_idx])
        p = m.predict(X[val_idx])
        pred[val_idx] = p
        by_fold.append(p)
        if proba:
            full = m.predict_proba(X[val_idx])
            for j, c in enumerate(m.classes_):
                P[val_idx, CLASSES.index(str(c))] = full[:, j]
    return (pred, by_fold, P) if proba else (pred, by_fold)


def measure_latency(model, X, n=300) -> dict:
    times = []
    for i in range(n):
        row = X[i % len(X)].reshape(1, -1)
        t = time.perf_counter()
        model.predict_proba(row)
        times.append((time.perf_counter() - t) * 1000)
    times.sort()
    return {"p50_ms": round(times[n // 2], 3), "p95_ms": round(times[int(n * 0.95)], 3),
            "throughput_per_s": round(1000 / (sum(times) / n), 1)}


def select_model(rows: list[dict]) -> dict:
    """Aturan pemilihan SDD 3.3: skor tertinggi, lalu yang lebih sederhana dalam selisih kecil."""
    eligible = [r for r in rows if r["kind"] == "candidate" and r["timing"]["latency"]["p95_ms"] <= MAX_LATENCY_P95_MS]
    if not eligible:
        raise TrainingError("Tidak ada kandidat yang memenuhi batas latensi")
    best = max(r["cv_macro_f1_mean"] for r in eligible)
    close = [r for r in eligible if best - r["cv_macro_f1_mean"] <= TIE_MARGIN]
    return min(close, key=lambda r: (SIMPLICITY[r["algorithm"]], FEATURE_PREFERENCE[r["feature_set"]], -r["cv_macro_f1_mean"], r["name"]))


def choose_threshold(y, P, rule_pred) -> dict:
    """Ambang probabilitas: macro-F1 tertinggi jika jendela di bawah ambang memakai aturan.

    Seri dipecah ke ambang terendah, agar model tidak digantikan aturan tanpa manfaat.
    """
    classes = np.array(CLASSES)
    top = P.max(axis=1)
    pred = classes[P.argmax(axis=1)]
    table = []
    for t in THRESHOLD_GRID:
        use = top >= t
        final = np.where(use, pred, rule_pred)
        table.append({"threshold": t, "hybrid_macro_f1": float(f1_score(y, final, labels=list(CLASSES), average="macro", zero_division=0)),
                      "coverage": float(use.mean()), "accuracy_when_used": float((pred[use] == y[use]).mean()) if use.any() else None})
    best = max(r["hybrid_macro_f1"] for r in table)
    chosen = next(r for r in table if best - r["hybrid_macro_f1"] <= 1e-9)
    return {"threshold": chosen["threshold"], "table": table,
            "rule": "macro-F1 out-of-fold tertinggi saat jendela di bawah ambang memakai aturan; seri ke ambang terendah"}


def learning_curve_points(model, X, y, rows, split, folds) -> list[dict]:
    groups = np.array([group_of(r) for r in rows])
    cycle_folds = split["cv_folds_leave_one_cycle_out"]
    if len(cycle_folds) < 3:
        return []
    all_cycles = {g for f in cycle_folds for g in f["validation"]}
    others = np.where(~np.isin(groups, list(all_cycles)))[0]
    points = []
    for k in range(1, len(cycle_folds)):
        scores = []
        for fold in cycle_folds:
            chosen = sorted(fold["train"])[:k]
            train_idx = np.concatenate([np.where(np.isin(groups, chosen))[0], others])
            val_idx = np.where(np.isin(groups, fold["validation"]))[0]
            if len(set(y[train_idx])) < 2 or not len(val_idx):
                continue
            pred = clone(model).fit(X[train_idx], y[train_idx]).predict(X[val_idx])
            scores.append(float(f1_score(y[val_idx], pred, labels=list(CLASSES), average="macro", zero_division=0)))
        if scores:
            points.append({"n_train_cycles": k, "macro_f1_mean": float(np.mean(scores)), "macro_f1_min": min(scores), "macro_f1_max": max(scores)})
    return points


def sanity_controls(model, X, y, folds, seed) -> dict:
    """Kontrol negatif dan contoh optimisme split per baris. Tidak dipakai untuk pemilihan."""
    rng = np.random.default_rng(seed)
    shuffled = rng.permutation(y)
    _, by_fold = oof_predict(model, X, shuffled, folds)
    control = float(np.mean(fold_scores(folds, shuffled, by_fold)))
    pred = np.empty(len(y), dtype=object)
    for a, b in StratifiedKFold(n_splits=5, shuffle=True, random_state=seed).split(X, y):
        pred[b] = clone(model).fit(X[a], y[a]).predict(X[b])
    return {"shuffled_label_macro_f1": control,
            "shuffled_label_warning": control > 0.5,
            "row_split_macro_f1_INVALID_for_reference_only": float(f1_score(y, pred, labels=list(CLASSES), average="macro", zero_division=0))}


def importance(model, names) -> tuple:
    clf = model.named_steps["clf"]
    if hasattr(clf, "feature_importances_"):
        return list(map(float, clf.feature_importances_)), "Importance (penurunan impurity)"
    if hasattr(clf, "coef_"):
        return list(map(float, np.abs(clf.coef_).max(axis=0))), "Nilai mutlak koefisien terbesar, setelah scaling"
    return None, None


def run(dataset_dir, split_path, models_root="models/development", reports_root="reports/experiments", seed=42, grid="full",
        sessions_root=None, include_svm=False, make_figures=True, log=print) -> dict:
    dataset_dir, split_path = Path(dataset_dir), Path(split_path)
    split = read_json(split_path)
    check_no_leakage(split)
    rows = load_dev_rows(dataset_dir, split)
    kind = rows[0]["data_kind"]
    y = np.array([r["label"] for r in rows])
    folds = group_folds(rows, split)
    seen = validated_rows(folds)
    majority = max(sorted(set(y)), key=lambda c: (y == c).sum())
    scorer = make_scorer(f1_score, average="macro", labels=list(CLASSES), zero_division=0)
    if kind != "real":
        log("[TRAIN] DATA SINTETIS: skor di bawah hanya menguji perangkat lunak.")
    elif not split["evaluation_ready"]:
        log("[TRAIN] PERINGATAN: data nyata belum memadai menurut split. Hasil hanya gambaran awal.")

    results, grids, oof = [], {}, {}
    algos = ["decision_tree", "logistic_regression", "random_forest"] + (["svm_rbf"] if include_svm else [])
    for algo in algos:
        for fset in ("F1", "F2", "F3"):
            names = feature_names(fset)
            X = matrix(rows, names)
            search = GridSearchCV(pipeline(algo, seed), GRIDS[grid][algo], scoring=scorer, cv=folds, n_jobs=1, refit=False, error_score="raise")
            t0 = time.perf_counter()
            search.fit(X, y)
            search_s = time.perf_counter() - t0
            model = pipeline(algo, seed).set_params(**search.best_params_)
            pred, by_fold = oof_predict(model, X, y, folds)
            scores = fold_scores(folds, y, by_fold)
            t0 = time.perf_counter()
            final = clone(model).fit(X, y)
            fit_s = time.perf_counter() - t0
            size = len(joblib_bytes(final))
            name = f"{algo}/{fset}"
            results.append({
                "name": name, "kind": "candidate", "algorithm": algo, "feature_set": fset,
                "params": {k.replace("clf__", ""): v for k, v in search.best_params_.items()},
                "cv_macro_f1_mean": float(np.mean(scores)), "cv_macro_f1_min": min(scores), "cv_macro_f1_max": max(scores),
                "cv_macro_f1_per_fold": scores, "oof_metrics": compute_metrics(y[seen], pred[seen]),
                "validation_holdout": holdout_metrics(model, X, y, rows, split),
                "n_grid": len(search.cv_results_["params"]),
                "artifact_bytes": size, "advantages": NOTES[algo][0], "limitations": NOTES[algo][1],
                "timing": {"search_s": round(search_s, 3), "fit_s": round(fit_s, 3), "latency": measure_latency(final, X)},
            })
            grids[name] = [{"params": p, "mean": float(m)} for p, m in zip(search.cv_results_["params"], search.cv_results_["mean_test_score"])]
            oof[name] = model
            log(f"[TRAIN] {name}: macro-F1 CV {np.mean(scores):.3f} (rentang {min(scores):.3f}-{max(scores):.3f})")

    results += baselines(rows, y, folds, majority, split, sessions_root, kind)
    chosen = select_model(results)
    names = feature_names(chosen["feature_set"])
    X = matrix(rows, names)
    model = oof[chosen["name"]]
    _, _, P = oof_predict(model, X, y, folds, proba=True)
    rule_pred = np.array([rule_activity(float(r["motion_rms_mean"]), float(r["rotation_rad_mean"])) for r in rows])
    threshold = choose_threshold(y[seen], P[seen], rule_pred[seen])
    top, classes = P[seen].max(axis=1), np.array(CLASSES)
    ece = expected_calibration_error(top.tolist(), (classes[P[seen].argmax(axis=1)] == y[seen]).astype(float).tolist())
    final = clone(model).fit(X, y)
    controls = sanity_controls(model, X, y, folds, seed)
    curve = learning_curve_points(model, X, y, rows, split, folds)
    best_baseline = max((r for r in results if r["kind"] == "baseline"), key=lambda r: r["cv_macro_f1_mean"])

    config_hash = hashlib.sha256(json.dumps({"w": split["windows_sha256"], "s": split["version"], "seed": seed, "grid": grid,
                                             "name": chosen["name"], "params": chosen["params"]}, sort_keys=True, default=str).encode()).hexdigest()[:8]
    version = f"{split['dataset_id']}-{split['version']}-{chosen['algorithm']}-{chosen['feature_set']}-{config_hash}"
    prefix = "" if kind == "real" else "SYNTHETIC_"
    model_dir = Path(models_root) / f"{prefix}{version}"
    model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, model_dir / "model.joblib")
    now = datetime.now(timezone.utc)
    exp_id = f"exp_{now:%Y%m%dT%H%M%S}_{config_hash}"
    span = X.max(axis=0) - X.min(axis=0)
    metadata = {
        "model_name": MODEL_NAME, "model_version": version, "training_timestamp": now.isoformat(), "experiment_id": exp_id,
        "algorithm": chosen["algorithm"], "feature_set": chosen["feature_set"], "hyperparameters": chosen["params"],
        "feature_schema_version": FEATURE_SCHEMA_VERSION, "feature_names": list(names), "classes": [str(c) for c in final.classes_],
        "label_mapping": {str(c): i for i, c in enumerate(final.classes_)},
        "feature_ranges": {n: {"low": float(X[:, i].min() - 0.5 * span[i]), "high": float(X[:, i].max() + 0.5 * span[i])} for i, n in enumerate(names)},
        "window": read_json(dataset_dir / "manifest.json")["window"], "smoothing_n": 5,
        "probability_threshold": threshold["threshold"], "probability_calibrated": False,
        "dataset_type": classify_dataset(rows), "data_kind": kind, "dataset_id": split["dataset_id"],
        "dataset_manifest_hash": sha256_file(dataset_dir / "manifest.json"), "windows_sha256": split["windows_sha256"],
        "split_file": str(split_path), "split_version": split["version"], "split_strategy": split["group_rule"] + "; validasi leave-one-cycle-out",
        "train_groups": split["train"], "validation_groups": split["validation"], "n_dev_windows": len(rows), "n_validated_windows": int(len(seen)), "majority_class": str(majority),
        "validation_results": {"cv_macro_f1_mean": chosen["cv_macro_f1_mean"], "cv_macro_f1_per_fold": chosen["cv_macro_f1_per_fold"], "oof_metrics": strip(chosen["oof_metrics"])},
        "test_results": None, "seed": seed,
        "versions": {"python": platform.python_version(), "scikit_learn": sklearn.__version__, "numpy": np.__version__, "joblib": joblib.__version__},
        "sha256": sha256_file(model_dir / "model.joblib"),
        "production_allowed": False,
        "status_claims": {"A_pipeline_implemented": True, "B_tested_with_synthetic": kind != "real", "C_trained_on_real": kind == "real",
                          "D_validated_on_heldout_real": False, "E_ready_for_production": False},
        "warnings": ([] if kind == "real" else ["MODEL SINTETIS. Bukan bukti performa pada mesin cuci."]) + split["warnings"],
    }
    write_json(model_dir / "metadata.json", metadata)

    exp_dir = Path(reports_root) / exp_id
    (exp_dir / "figures").mkdir(parents=True, exist_ok=True)
    importance_values, importance_title = importance(final, names)
    report = {
        "experiment_id": exp_id, "training_timestamp": now.isoformat(), "data_kind": kind, "dataset_type": classify_dataset(rows),
        "dataset_id": split["dataset_id"], "split_version": split["version"], "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "seed": seed, "grid": grid, "n_folds": len(folds), "versions": metadata["versions"], "environment": platform.platform(),
        "selection_rule": f"macro-F1 CV tertinggi; selisih <= {TIE_MARGIN} memilih yang lebih sederhana; p95 <= {MAX_LATENCY_P95_MS} ms",
        "selected": chosen["name"], "model_dir": str(model_dir), "beats_best_baseline": chosen["cv_macro_f1_mean"] > best_baseline["cv_macro_f1_mean"],
        "best_baseline": best_baseline["name"], "threshold": threshold, "calibration": {"ece_oof": ece, "calibrated": False},
        "pause_analysis_dev": pause_report(rows, sessions_root),
        "controls": controls, "learning_curve": curve, "grids": grids, "split_warnings": split["warnings"],
        "feature_importance": dict(zip(names, importance_values)) if importance_values else None,
        "comparison": [{**r, "oof_metrics": strip(r["oof_metrics"])} for r in results],
    }
    write_json(exp_dir / "metrics.json", report)
    write_comparison_csv(exp_dir / "comparison.csv", results)
    append_index(Path(reports_root) / "index.csv", report, chosen, split, str(model_dir))
    if make_figures:
        fig = exp_dir / "figures"
        figures.class_distribution({k: split["n_windows_per_label"][k] for k in ("train", "validation")} | {"test": split["n_windows_per_label"]["test"]}, kind, fig / "class_distribution.png")
        figures.model_comparison(results, kind, fig / "model_comparison.png")
        figures.confusion(chosen["oof_metrics"], f"Confusion matrix out-of-fold: {chosen['name']}", kind, fig / "confusion_oof.png")
        if importance_values:
            figures.feature_importance(names, importance_values, importance_title, kind, fig / "feature_importance.png")
        if curve:
            figures.learning_curve(curve, kind, fig / "learning_curve.png")
    log(f"[TRAIN] Terpilih {chosen['name']}. Model: {model_dir}. Laporan: {exp_dir}")
    return {"model_dir": model_dir, "experiment_dir": exp_dir, "report": report, "metadata": metadata}


def pause_report(rows, sessions_root):
    """Dasar penetapan CUCI_DONE_S. Hanya siklus pengembangan, tanpa siklus test."""
    if not sessions_root:
        return None
    ids = sorted({r["session_id"] for r in rows if r["session_type"] == "cycle"})
    return replay.pause_analysis([Path(sessions_root) / s for s in ids])


def joblib_bytes(model) -> bytes:
    import io
    buffer = io.BytesIO()
    joblib.dump(model, buffer)
    return buffer.getvalue()


def strip(metrics: dict) -> dict:
    return {k: v for k, v in metrics.items() if k != "classification_report"}


def holdout_metrics(model, X, y, rows, split):
    groups = np.array([group_of(r) for r in rows])
    train_idx = np.where(np.isin(groups, split["train"]))[0]
    val_idx = np.where(np.isin(groups, split["validation"]))[0]
    if not len(val_idx) or len(set(y[train_idx])) < 2:
        return None
    pred = clone(model).fit(X[train_idx], y[train_idx]).predict(X[val_idx])
    return strip(compute_metrics(y[val_idx], pred))


def baselines(rows, y, folds, majority, split, sessions_root, kind) -> list[dict]:
    out = []
    X = matrix(rows, feature_names("F2"))
    dummy = Pipeline([("clf", DummyClassifier(strategy="most_frequent"))])
    pred, by_fold = oof_predict(dummy, X, y, folds)
    out.append(_baseline_row("baseline_mayoritas", "Tebakan kelas terbanyak", y, folds, pred, by_fold, "Batas bawah sederhana", "Tidak membedakan apa pun"))
    rule = np.array([rule_activity(float(r["motion_rms_mean"]), float(r["rotation_rad_mean"])) for r in rows], dtype=object)
    out.append(_baseline_row("baseline_ambang", "Ambang Config lama per jendela agregat. Bukan ML", y, folds, rule, [rule[v] for _, v in folds],
                             "Tidak perlu data training", "Tanpa ingatan, ambang ditulis manusia, peka offset"))
    if sessions_root:
        series = {}
        pred = np.empty(len(rows), dtype=object)
        for i, row in enumerate(rows):
            sid = row["session_id"]
            if sid not in series:
                series[sid] = replay.replay_legacy(Path(sessions_root) / sid)
            pred[i] = replay.activity_at(series[sid], [int(row["window_end_ms"])])[0]
        out.append(_baseline_row("baseline_fsm_lama", "FSM lama mode real, state dipetakan ke aktivitas. DONE dianggap IDLE", y, folds, pred, [pred[v] for _, v in folds],
                                 "Perilaku nyata sistem lama", "Tertinggal karena syarat durasi dan moving average; pemetaan tidak sepenuhnya sebanding"))
    return out


def _baseline_row(name, params, y, folds, pred, by_fold, adv, lim):
    scores = fold_scores(folds, y, by_fold)
    seen = validated_rows(folds)
    return {"name": name, "kind": "baseline", "algorithm": name, "feature_set": "-", "params": params,
            "cv_macro_f1_mean": float(np.mean(scores)), "cv_macro_f1_min": min(scores), "cv_macro_f1_max": max(scores),
            "cv_macro_f1_per_fold": scores, "oof_metrics": compute_metrics(y[seen], pred[seen]), "validation_holdout": None, "n_grid": 0,
            "artifact_bytes": None, "advantages": adv, "limitations": lim, "timing": None}


def write_comparison_csv(path: Path, results: list[dict]):
    columns = ("name", "kind", "params", "cv_macro_f1_mean", "cv_macro_f1_min", "cv_macro_f1_max", "accuracy", "balanced_accuracy", "weighted_f1",
               "active_predicted_idle_rate", "fit_s", "latency_p95_ms", "artifact_bytes", "advantages", "limitations")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        for r in sorted(results, key=lambda r: -r["cv_macro_f1_mean"]):
            m = r["oof_metrics"]
            t = r["timing"] or {}
            w.writerow({"name": r["name"], "kind": r["kind"], "params": json.dumps(r["params"], default=str), "cv_macro_f1_mean": round(r["cv_macro_f1_mean"], 4),
                        "cv_macro_f1_min": round(r["cv_macro_f1_min"], 4), "cv_macro_f1_max": round(r["cv_macro_f1_max"], 4), "accuracy": round(m["accuracy"], 4),
                        "balanced_accuracy": round(m["balanced_accuracy"], 4), "weighted_f1": round(m["weighted_f1"], 4), "active_predicted_idle_rate": m["active_predicted_idle_rate"],
                        "fit_s": t.get("fit_s"), "latency_p95_ms": (t.get("latency") or {}).get("p95_ms"), "artifact_bytes": r["artifact_bytes"],
                        "advantages": r["advantages"], "limitations": r["limitations"]})


def append_index(path: Path, report: dict, chosen: dict, split: dict, model_dir: str):
    columns = ("experiment_id", "training_timestamp", "data_kind", "dataset_id", "split_version", "feature_schema_version", "model_type", "feature_set",
               "hyperparameters", "cv_macro_f1", "beats_best_baseline", "seed", "model_artifact")
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerow({"experiment_id": report["experiment_id"], "training_timestamp": report["training_timestamp"], "data_kind": report["data_kind"],
                    "dataset_id": report["dataset_id"], "split_version": report["split_version"], "feature_schema_version": report["feature_schema_version"],
                    "model_type": chosen["algorithm"], "feature_set": chosen["feature_set"], "hyperparameters": json.dumps(chosen["params"], default=str),
                    "cv_macro_f1": round(chosen["cv_macro_f1_mean"], 4), "beats_best_baseline": report["beats_best_baseline"], "seed": report["seed"], "model_artifact": model_dir})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Latih model aktivitas WashAlert AI")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--split", required=True, help="Versi split, misalnya v1")
    parser.add_argument("--processed-root", default="data/processed")
    parser.add_argument("--manifests", default="data/manifests")
    parser.add_argument("--sessions-root", help="Folder sesi. Bawaan data/real atau data/synthetic sesuai dataset")
    parser.add_argument("--models-root", default="models/development")
    parser.add_argument("--reports-root", default="reports/experiments")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--grid", choices=sorted(GRIDS), default="full")
    parser.add_argument("--include-svm", action="store_true")
    args = parser.parse_args(argv)
    dataset_dir = Path(args.processed_root) / args.dataset
    split_path = Path(args.manifests) / f"split_{args.dataset}_{args.split}.json"
    try:
        sessions = args.sessions_root
        if not sessions:
            kind = read_json(split_path)["data_kind"]
            candidate = Path("data") / kind
            sessions = str(candidate) if candidate.exists() else None
        result = run(dataset_dir, split_path, args.models_root, args.reports_root, args.seed, args.grid, sessions, args.include_svm)
    except (TrainingError, ValueError, OSError) as exc:
        print(f"[TRAIN] Ditolak: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result["report"]["controls"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
