# Laporan Phase 5: Pengembangan Model

Tanggal 4 November 2026.

> **Pipeline selesai dan diuji dengan data sintetis. Belum ada model dari data nyata.** Detector belum memakai model.

| Tingkat | Status |
|---|---|
| A. Pipeline diimplementasikan | Ya |
| B. Pipeline diuji dengan data sintetis | Ya |
| C. Model dilatih dengan data nyata | Belum |
| D. Model divalidasi dengan held-out nyata | Belum |
| E. Siap integrasi produksi | Belum |

## Kesiapan dataset

| Dataset | Kelas | Isi | Pakai untuk |
|---|---|---|---|
| `data/real/` | REAL | Kosong | Menunggu pengumpulan data |
| `syn_hard_v1` | SYNTHETIC | 8 siklus + 2 sesi idle buatan, 4.568 jendela | Smoke test |

Tidak ada dataset MIXED, dan pipeline menolaknya.

## Hasil dan dokumen

- Hasil rinci: `ml_evaluation_report.md`.
- Cara menjalankan dan API inference: `ml_training_guide.md`.
- Status kebutuhan: `requirements_traceability_matrix.md`.
- Perubahan terkontrol: CR-008 di `requirements_baseline_and_changelog.md`.

## Keterbatasan

- Skor sintetis tidak menunjukkan performa nyata, dan sebagian keunggulan atas baseline berasal dari asumsi generator.
- Baseline ambang tanpa ingatan, dan FSM lama yang dipetakan, tidak sepenuhnya sebanding dengan model.
- End-to-end hanya arm 1. Arm 2 sampai 4 menunggu Phase 6.
- Sesi non-siklus selalu di training, sehingga gangguan hanya diuji jika masuk test.
- Decision Tree terpilih dengan selisih kecil. Pilihan dapat berubah pada data nyata.
- Probabilitas belum dikalibrasi.
- Latensi diukur di container cloud.
- Versi ML tersemat diuji pada Python 3.13 di Linux saja.
