# Dokumentasi Machine Learning WashAlert AI

> Semua angka di dokumen ini berasal dari data **sintetis**. Angka hanya membuktikan pipeline berjalan. Evaluasi pada mesin cuci nyata belum dilakukan.

Sumber angka: `docs/ml_evaluation_report.md`, eksperimen `exp_20261104T141944_624d6645`.

## 1. Mengapa WashAlert membutuhkan ML

Audit Phase 1 menemukan bahwa ambang tetap rapuh. Offset RMS 0,15 mencegah DONE, sedangkan offset 0,26 ke atas memicu WASHING palsu (A-05). `motion_rms` hampir tidak melihat getaran horizontal (A-03). Nilai yang tepat juga akan berbeda antar HP, posisi, dan mesin.

Alasan memakai ML adalah **hipotesis yang belum terbukti**: pola beberapa fitur mungkin lebih tahan terhadap perbedaan itu daripada satu ambang, jika dilatih dari rekaman mesin nyata. Sebagian perbaikan terbesar justru bukan dari ML, melainkan dari FSM dan penanganan galat.

## 2. Aturan dan machine learning

| Aspek | Berbasis aturan | Machine learning |
|---|---|---|
| Asal keputusan | Ambang yang ditulis manusia | Pola yang dipelajari dari data berlabel |
| Butuh data berlabel | Tidak | Ya |
| Artefak | Kode dan konfigurasi | `model.joblib` hasil training |
| Di WashAlert AI | `RULE_ONLY`, fallback, seluruh FSM | Aktivitas pada `HYBRID` dan `ML_ONLY` |

FSM dengan ambang **bukan** ML, karena tidak ada proses belajar dari data.

## 3. Input sensor

Accelerometer (m/s²) dan gyroscope (rad/s) tiga sumbu dari HP A. Edge menghitung fitur per jendela 5 sampel dan mengirimnya lewat MQTT, sedangkan detector mengagregasi jendela itu.

## 4. Target label

`IDLE`, `WASHING`, dan `SPIN`. `DONE` bukan kelas, karena tidak dapat diamati dari getaran.

## 5. Ground truth

Label berasal dari pengamatan manusia, langsung atau lewat video, sesuai `docs/labeling_protocol.md`. Label pada data saat ini dibuat generator, sehingga bukan observasi.

## 6. Rekayasa fitur

Fitur dasar ada di `shared/features.py`, dan dipakai sama oleh edge, pembuatan dataset, serta inference.

| Set | Fitur dasar | Kolom |
|---|---|---:|
| F1 | `motion_rms`, `rotation_rad` | 6 |
| F2 | `acc_dyn_rms`, `acc_mag_ptp`, `gyro_rms`, `gyro_max` | 12 |
| F3 | F1 + F2 | 18 |

Tiap fitur dirangkum menjadi rata-rata, SD, dan maksimum dalam 30 detik terakhir. Jendela agregat butuh minimal 3 jendela edge dan cakupan 20 detik. Nilai-nilai ini masih usulan. Detail: `docs/feature_engineering.md`.

## 7. Pembagian dataset

Pembagian dilakukan per siklus, tidak per baris. Dataset `syn_hard_v1` berisi 8 siklus dan 2 sesi idle. Sebanyak 6 siklus dipakai pengembangan (4 training dan 2 validation, ditambah cross-validation leave-one-cycle-out) dan 2 siklus (C04, C05) menjadi test. Data pengembangan berjumlah 3.513 jendela, test 1.055 jendela.

## 8. Pencegahan kebocoran data

- Jendela dari satu siklus tidak pernah berada di dua bagian.
- File split dikunci dengan hash, dan grup test dibuang sebelum training.
- Jendela dekat pergantian label dibuang.
- Kolom identitas, waktu, dan status FSM tidak masuk fitur.
- Test hanya boleh dibuka sekali, dan tercatat.

Kontrol pada eksperimen ini:

| Validasi | Macro-F1 | Arti |
|---|---:|---|
| Per siklus, yang dipakai | 0,848 | Skor sah |
| Label diacak | 0,224 | Mendekati tebakan, tidak ada tanda kebocoran fitur |
| Split acak per baris, tidak sah | 0,948 | Lebih tinggi karena jendela siklus sama bocor |

## 9. Algoritma yang dievaluasi

Logistic Regression, Decision Tree, dan Random Forest pada F1, F2, F3. Pembandingnya baseline mayoritas, ambang, dan FSM lama. SVM tersedia sebagai opsi, tetapi tidak dijalankan pada eksperimen ini. Deep learning tidak dipakai karena tidak ada alasan yang mendukungnya pada data sekecil ini.

## 10. Hyperparameter

`GridSearchCV` kecil dengan fold per siklus. Hasil terpilih decision tree: `max_depth=8`, `min_samples_leaf=1`.

## 11. Pemilihan model

Aturan ditetapkan sebelum test dibuka: macro-F1 CV tertinggi; jika selisih ≤ 0,01 pilih yang lebih sederhana; latensi p95 ≤ 100 ms.

| Model | Macro-F1 CV (rentang fold) | p95 (ms) | Ukuran (KB) |
|---|---:|---:|---:|
| decision_tree/F2 **terpilih** | 0,848 (0,670–0,957) | 0,264 | 9,1 |
| random_forest/F3 | 0,838 (0,707–0,934) | 15,06 | 1.855,9 |
| random_forest/F2 | 0,827 (0,687–0,934) | 12,843 | 2.051,0 |
| logistic_regression/F3 | 0,805 (0,552–0,960) | 0,562 | 2,2 |
| baseline ambang | 0,494 (0,111–0,967) | Tidak diukur | Tidak ada |
| baseline mayoritas | 0,268 (0,268–0,269) | Tidak diukur | Tidak ada |

Selisih antar kandidat jauh lebih kecil dari rentang antar fold, sehingga pilihan ini lemah secara statistik dan dapat berubah pada data nyata. Latensi diukur di container cloud.

## 12. Metrik

Macro-F1 menjadi metrik utama, karena WASHING mendominasi: baseline yang selalu menebak kelas terbanyak mendapat accuracy 0,673 tetapi macro-F1 hanya 0,268. Tingkat siklus memakai alert palsu, alert terlewat, dan keterlambatan.

| Metode pada test | Macro-F1 | Accuracy |
|---|---:|---:|
| Model terpilih | 0,920 | 0,937 |
| Baseline ambang | 0,628 | 0,531 |
| FSM lama dipetakan | 0,607 | 0,587 |
| Baseline mayoritas | 0,268 | 0,673 |

Skor test lebih tinggi dari CV hanya karena dua siklus test kebetulan lebih mudah.

## 13. Confusion matrix (test sintetis)

| Label \ Prediksi | IDLE | SPIN | WASHING |
|---|---:|---:|---:|
| IDLE | 144 | 0 | 34 |
| SPIN | 0 | 167 | 0 |
| WASHING | 0 | 32 | 678 |

Kesalahan terbesar adalah IDLE dengan getaran latar yang terbaca WASHING. Ini dapat memperlambat deteksi selesai, dan memang terlihat pada bagian 16.

## 14. Inference

```text
telemetri v2 → validasi → jendela agregat 30 dtk → model → smoothing mayoritas N=5 → FSM
```

Model dimuat sekali saat start. Hash file, skema fitur, kelas, dan versi pustaka diperiksa sebelum dipakai. Median latensi saat demo sekitar 0,56 ms. Probabilitas belum terkalibrasi (ECE 0,141), jadi tidak ditampilkan sebagai confidence.

## 15. Hybrid ML + FSM

| Keputusan | Asal |
|---|---|
| Aktivitas saat ini | Model, atau aturan saat fallback |
| Mulai siklus, DONE, alert, pengingat, konfirmasi, koreksi | FSM |
| Fallback | `activity.py` |

**Mengapa IDLE tidak berarti DONE.** Mesin yang diam bisa menunggu mulai, jeda antar fase, atau selesai. Getaran pada tiga keadaan itu sama. Yang membedakan adalah riwayat: apakah mesin sudah bekerja cukup lama dan sudah diam cukup lama. Karena model hanya melihat 30 detik terakhir, keputusan itu diserahkan kepada FSM.

## 16. Mencegah alert palsu

Durasi kerja minimum, batas diam, batas lebih lama jika belum ada spin, smoothing, syarat dua dari tiga jendela untuk memulai, data rusak menahan timer, serta koreksi jika mesin aktif lagi.

Perbandingan pada 2 siklus test sintetis, mode real:

| Kelompok | Terdeteksi | Terlewat | Alert palsu | Keterlambatan |
|---|---:|---:|---:|---:|
| 1 FSM lama | 0/2 | 2 | 0 | Tidak ada |
| 2 FSM baru + aturan | 0/2 | 2 | 0 | Tidak ada |
| 3 HYBRID | 1/2 | 1 | 0 | 155,2 dtk |
| 4 ML_ONLY | 1/2 | 1 | 0 | 161,4 dtk |

**ML belum terbukti lebih unggul.** Model hanya unggul pada data dari generator yang sama, yang sengaja memasukkan getaran latar tepat di ambang diam, dan dengan hanya 2 siklus. Satu siklus tetap terlewat. Rekaman juga berhenti sekitar 180 detik setelah mesin berhenti, sehingga deteksi yang lebih lambat tidak teramati. Jika pada data nyata model tidak lebih baik, kesimpulan yang jujur adalah mempertahankan `RULE_ONLY` dengan FSM baru.

## 17. Keterbatasan model

- Dilatih dari generator yang saya tulis sendiri, sehingga asumsinya mempengaruhi hasil.
- Hanya satu "mesin" sintetis, sehingga generalisasi antar mesin belum diuji.
- Saat demo, data berlabel WASHING pada C05 sering terbaca SPIN.
- Keluaran pohon berubah-ubah pada data IDLE, yang dapat menunda DONE.
- Ambang probabilitas terpilih 0, sehingga fallback probabilitas rendah tidak aktif pada model ini.
- Artefak terikat versi scikit-learn.

## 18. Status validasi

| Tingkat | Status |
|---|---|
| Pipeline diimplementasikan dan diuji pada data sintetis | Ya |
| Model terhubung ke detector | Ya, uji perangkat lunak |
| Model dilatih dan divalidasi dengan data nyata | **Belum** |
| Layak produksi | **Tidak** |

Label "AI" pada nama proyek merujuk hanya pada classifier aktivitas di `HYBRID` dan `ML_ONLY`.
