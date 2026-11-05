# Panduan Training dan Inference: WashAlert AI

## 1. Masalah ML

| Unsur | Definisi | Kebutuhan terkait |
|---|---|---|
| Jenis | Supervised multiclass classification | Prediksi aktivitas, SDD 3.1 |
| Input X | Statistik 30 detik terakhir dari fitur accelerometer dan gyroscope, `shared/features.py` | Daftar fitur, Jendela agregat |
| Target y | `IDLE`, `WASHING`, `SPIN` dari observasi manusia | Definisi kelas |
| Bukan target | `DONE`. Keputusan ini tetap milik FSM | Pemisahan aktivitas dan keputusan |

Tidak ada kolom identitas, waktu, status FSM, atau nama file di dalam X. Tidak ada imputasi: data rusak dibuang sebelum dataset, dan saat runtime jendela itu memakai aturan.

## 2. Pemasangan

Hanya di laptop. HP tidak memerlukan paket ini.

```bash
pip install -r requirements-ml.txt
```

Versi tersemat telah diuji pada Python 3.13, dan NumPy 2.5 membutuhkan Python ≥ 3.12. Pada Python lebih lama, sematkan versi lain yang kompatibel, lalu jalankan ulang test dan training. Model hanya dapat dimuat pada versi mayor.minor scikit-learn yang sama.

## 3. Data nyata

```bash
python -m ml.validate_dataset --root data/real
python -m ml.build_dataset --root data/real --dataset-id real_v1
python -m ml.split_dataset --dataset real_v1 --version v1   # commit file split SEBELUM training final
python -m ml.train --dataset real_v1 --split v1
# Periksa laporan pada data pengembangan. Jika pipeline perlu diubah, ubah sekarang.
python -m ml.evaluate --model-dir models/development/<versi>   # sekali saja
```

## 4. Uji pipeline dengan data sintetis

```bash
python -m ml.generate_synthetic --difficulty hard
python -m ml.build_dataset --root data/synthetic --dataset-id syn_hard_v1
python -m ml.split_dataset --dataset syn_hard_v1 --version v1
python -m ml.train --dataset syn_hard_v1 --split v1
python -m ml.evaluate --model-dir models/development/SYNTHETIC_<versi>
```

Hasilnya tidak boleh dilaporkan sebagai performa. Folder model diberi awalan `SYNTHETIC_`, dan inference menolaknya tanpa izin eksplisit.

## 5. Yang dilakukan training

1. Memeriksa hash dataset dan split, lalu membuang grup test.
2. Menolak dataset MIXED.
3. Membuat fold leave-one-cycle-out.
4. Mencari hyperparameter dengan `GridSearchCV` pada fold itu, untuk tiap kandidat dan set fitur F1, F2, F3. Grid sengaja kecil, karena data diperkirakan sedikit.
5. Menghitung baseline mayoritas, ambang, dan FSM lama. Dua terakhir bukan model ML.
6. Memilih model dengan aturan tetap: macro-F1 CV tertinggi; jika selisih ≤ 0,01, pilih yang lebih sederhana; p95 ≤ 100 ms.
7. Memilih ambang probabilitas dari prediksi out-of-fold.
8. Menjalankan kontrol label acak dan contoh split per baris.
9. Melatih ulang pada seluruh data pengembangan, lalu menyimpan model dan metadata.

SVM opsional: `--include-svm`. Tidak aktif secara bawaan karena probabilitasnya mahal dan belum ada bukti manfaat.

## 6. Keluaran

```text
models/development/<versi>/        model.joblib, metadata.json
reports/experiments/index.csv      catatan semua eksperimen
reports/experiments/<exp_id>/      metrics.json, comparison.csv, test_report.json, figures/
reports/experiments/test_access_log.csv   setiap pembukaan test set
```

Evaluasi kedua untuk model yang sama ditolak, kecuali `--allow-reevaluation`, dan tetap tercatat.

## 7. Inference

```python
from nodes.detector_service.inference import try_load

model, reason = try_load("models/production/<versi>")
if model is None:
    # reason menjadi fallback_reason, mode efektif RULE_ONLY
    ...
result = model.predict(buffer.aggregate())
activity = rule_activity_value if result.use_fallback else result.activity
```

| Alasan muat gagal | Arti |
|---|---|
| `model_missing`, `metadata_missing`, `metadata_invalid` | File tidak ada atau rusak |
| `synthetic_not_allowed` | Model sintetis tanpa izin eksplisit |
| `feature_schema_mismatch` | Definisi fitur berbeda |
| `model_hash_mismatch` | File berubah. Tidak dideserialisasi |
| `dependency_missing`, `dependency_mismatch` | scikit-learn tidak ada, atau versinya berbeda |
| `model_invalid` | Rusak atau belum dilatih |

| `predict` | Arti | Tindakan detector |
|---|---|---|
| `ok=False`, `missing_features`, `invalid_features`, `unexpected_features`, `prediction_error` | Masukan atau prediksi gagal | Aturan |
| `low_probability` | Di bawah ambang | Aturan |
| `out_of_training_range` | Di luar rentang training + 50% | Aturan |

Fitur F3 yang tidak dipakai model diabaikan, karena `AggregateBuffer` selalu menghasilkan semuanya. Nama lain ditolak.

Coba satu baris:

```bash
python -m ml.predict --model-dir models/development/<versi> --windows data/processed/<id>/windows.csv --row 0
```

## 8. Keamanan artefak

Pemeriksaan hash mencegah file salah atau rusak. Ini bukan perlindungan dari orang yang dapat mengubah model dan metadata sekaligus. Jangan memuat `.joblib` dari sumber lain.

## 9. Syarat promosi ke `models/production/`

Data nyata, `evaluation_ready=true`, test sudah dievaluasi sekali, laporan batasan ditulis, dan kelompok menyetujui. Promosi dilakukan manual, tidak otomatis.
