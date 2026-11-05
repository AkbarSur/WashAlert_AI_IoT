"""Grafik evaluasi. Setiap grafik menyatakan asal data agar tidak disangka hasil eksperimen nyata."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
CLASS_COLOR = {"IDLE": "#1baf7a", "WASHING": "#2a78d6", "SPIN": "#eb6834"}
SEQ = LinearSegmentedColormap.from_list("seq", ["#f4f7fb", "#2a78d6", "#123a6b"])
plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED,
                     "ytick.color": MUTED, "text.color": INK, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE})


def banner(data_kind: str) -> str:
    if data_kind == "real":
        return "Sumber: rekaman nyata"
    return "DATA SINTETIS: hanya menguji perangkat lunak, bukan performa pada mesin cuci"


def _finish(fig, ax, title, data_kind, path):
    fig.suptitle(title, x=0.02, ha="left", fontsize=12, fontweight="bold")
    fig.text(0.02, 0.905, banner(data_kind), ha="left", fontsize=9, color=MUTED, fontweight="bold" if data_kind != "real" else "normal")
    fig.tight_layout(rect=(0, 0, 1, 0.89))
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _clean(ax, axis="y"):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis=axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def class_distribution(counts: dict, data_kind: str, path):
    parts = list(counts)
    fig, ax = plt.subplots(figsize=(7, 4))
    left = [0] * len(parts)
    for c in ("IDLE", "WASHING", "SPIN"):
        values = [counts[p].get(c, 0) for p in parts]
        ax.barh(parts, values, left=left, color=CLASS_COLOR[c], label=c, edgecolor=SURFACE, linewidth=2, height=0.55)
        left = [a + b for a, b in zip(left, values)]
    for y, total in enumerate(left):
        ax.text(total, y, f" {total}", va="center", color=MUTED)
    ax.invert_yaxis()
    ax.set_xlabel("Jumlah jendela agregat")
    ax.legend(frameon=False, ncol=3, loc="lower right")
    _clean(ax, "x")
    _finish(fig, ax, "Distribusi kelas per bagian dataset", data_kind, path)


def confusion(metrics: dict, title: str, data_kind: str, path):
    cm = metrics["confusion_matrix"]
    labels, m = cm["labels"], cm["rows_true_cols_pred"]
    fig, ax = plt.subplots(figsize=(5.4, 4.8))
    totals = [sum(r) or 1 for r in m]
    norm = [[v / t for v in r] for r, t in zip(m, totals)]
    ax.imshow(norm, cmap=SEQ, vmin=0, vmax=1)
    ax.set_xticks(range(len(labels)), labels)
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlabel("Prediksi")
    ax.set_ylabel("Label observasi")
    for i, row in enumerate(m):
        for j, v in enumerate(row):
            ax.text(j, i, f"{v}\n{norm[i][j]:.0%}", ha="center", va="center", color="white" if norm[i][j] > 0.55 else INK, fontsize=9)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    _finish(fig, ax, title, data_kind, path)


def model_comparison(rows: list[dict], data_kind: str, path):
    rows = sorted(rows, key=lambda r: r["cv_macro_f1_mean"])
    names = [r["name"] for r in rows]
    values = [r["cv_macro_f1_mean"] for r in rows]
    colors = ["#a9a8a3" if r["kind"] == "baseline" else "#2a78d6" for r in rows]
    fig, ax = plt.subplots(figsize=(8, max(3.4, 0.36 * len(rows) + 1.6)))
    ax.barh(names, values, color=colors, height=0.55)
    for y, r in enumerate(rows):
        low, high = r["cv_macro_f1_min"], r["cv_macro_f1_max"]
        ax.plot([low, high], [y, y], color=INK, linewidth=1.2)
        ax.text(1.02, y, f"{r['cv_macro_f1_mean']:.3f}", va="center", color=MUTED, fontsize=9)
    ax.set_xlim(0, 1.1)
    ax.set_xlabel("Macro-F1 cross-validation per siklus. Garis: rentang antar-fold. Abu-abu: baseline")
    _clean(ax, "x")
    _finish(fig, ax, "Perbandingan kandidat pada data pengembangan", data_kind, path)


def feature_importance(names, values, title, data_kind, path):
    pairs = sorted(zip(names, values), key=lambda p: p[1])[-12:]
    fig, ax = plt.subplots(figsize=(7, max(3.2, 0.32 * len(pairs) + 1.5)))
    ax.barh([p[0] for p in pairs], [p[1] for p in pairs], color="#2a78d6", height=0.55)
    ax.set_xlabel(title)
    _clean(ax, "x")
    _finish(fig, ax, "Fitur yang paling berpengaruh pada model terpilih", data_kind, path)


def learning_curve(points: list[dict], data_kind: str, path):
    fig, ax = plt.subplots(figsize=(7, 4))
    x = [p["n_train_cycles"] for p in points]
    ax.plot(x, [p["macro_f1_mean"] for p in points], color="#2a78d6", linewidth=2, marker="o", markersize=8)
    ax.fill_between(x, [p["macro_f1_min"] for p in points], [p["macro_f1_max"] for p in points], color="#2a78d6", alpha=0.12, linewidth=0)
    ax.set_xticks(x)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("Jumlah siklus untuk training")
    ax.set_ylabel("Macro-F1 pada siklus lain")
    _clean(ax)
    _finish(fig, ax, "Kurva belajar, dipisah per siklus", data_kind, path)


def timeline(rows: list[dict], preds: list[str], title: str, data_kind: str, path):
    t0 = int(rows[0]["window_end_ms"])
    minutes = [(int(r["window_end_ms"]) - t0) / 60000 for r in rows]
    fig, (a, b) = plt.subplots(2, 1, figsize=(10, 4.8), sharex=True, gridspec_kw={"height_ratios": [2.4, 1]})
    a.plot(minutes, [float(r["acc_dyn_rms_mean"]) for r in rows], color="#2a78d6", linewidth=1.6)
    a.set_ylabel("acc_dyn_rms_mean (m/s²)")
    _clean(a)
    for y, seq in ((1, [r["label"] for r in rows]), (0, preds)):
        b.scatter(minutes, [y] * len(minutes), c=[CLASS_COLOR[s] for s in seq], s=14, marker="s", linewidths=0)
    b.set_yticks([0, 1], ["Prediksi", "Label"])
    b.set_ylim(-0.6, 1.6)
    b.set_xlabel("Menit. Celah: jendela dekat perubahan fase tidak masuk dataset")
    for s in b.spines.values():
        s.set_visible(False)
    for c, color in CLASS_COLOR.items():
        b.scatter([], [], c=color, s=30, marker="s", label=c)
    b.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.45))
    _finish(fig, a, title, data_kind, path)
