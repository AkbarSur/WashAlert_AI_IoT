"""Metrik klasifikasi aktivitas (DML metrik aktivitas). Tidak mengukur keberhasilan notifikasi."""

from sklearn.metrics import (accuracy_score, balanced_accuracy_score, classification_report, confusion_matrix,
                             precision_recall_fscore_support)

CLASSES = ("IDLE", "SPIN", "WASHING")
ACTIVE = ("WASHING", "SPIN")


def compute_metrics(y_true, y_pred, classes=CLASSES) -> dict:
    labels = list(classes)
    macro = precision_recall_fscore_support(y_true, y_pred, labels=labels, average="macro", zero_division=0)
    weighted = precision_recall_fscore_support(y_true, y_pred, labels=labels, average="weighted", zero_division=0)
    p, r, f, s = precision_recall_fscore_support(y_true, y_pred, labels=labels, average=None, zero_division=0)
    y_true, y_pred = list(y_true), list(y_pred)
    active = [i for i, y in enumerate(y_true) if y in ACTIVE]
    return {
        "n": len(y_true),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)) if y_true else 0.0,
        "macro_precision": float(macro[0]), "macro_recall": float(macro[1]), "macro_f1": float(macro[2]),
        "weighted_f1": float(weighted[2]),
        "per_class": {c: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]), "support": int(s[i])}
                      for i, c in enumerate(labels)},
        "confusion_matrix": {"labels": labels, "rows_true_cols_pred": confusion_matrix(y_true, y_pred, labels=labels).tolist()},
        "active_predicted_idle_rate": (sum(y_pred[i] == "IDLE" for i in active) / len(active)) if active else None,
        "classification_report": classification_report(y_true, y_pred, labels=labels, zero_division=0, digits=3),
    }


def expected_calibration_error(max_probs, correct, bins: int = 10) -> float:
    """Selisih rata-rata antara probabilitas tertinggi dan ketepatan, per kelompok nilai."""
    total, error = len(max_probs), 0.0
    for b in range(bins):
        low, high = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(max_probs) if low < p <= high or (b == 0 and p == 0)]
        if idx:
            error += len(idx) / total * abs(sum(max_probs[i] for i in idx) / len(idx) - sum(correct[i] for i in idx) / len(idx))
    return error


def longest_false_idle_seconds(rows, y_pred) -> float:
    """Durasi terpanjang saat mesin aktif tetapi diprediksi IDLE. Risiko langsung bagi false DONE.

    rows berurutan waktu dalam satu sesi, dengan kolom window_end_ms dan label.
    """
    longest = 0.0
    start = None
    for row, pred in zip(rows, y_pred):
        t = int(row["window_end_ms"])
        if row["label"] in ACTIVE and pred == "IDLE":
            start = start if start is not None else t
            longest = max(longest, (t - start) / 1000)
        else:
            start = None
    return longest
