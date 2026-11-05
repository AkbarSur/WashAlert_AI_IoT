# Skema Dataset: WashAlert AI

Versi 0.2, sesuai implementasi Phase 4 (`ml/dataset_io.py`, `ml/build_dataset.py`).

> **Semua baris contoh di dokumen ini ILUSTRATIF.** Angkanya saya tulis untuk menunjukkan format. Angka ini bukan hasil pengukuran dan tidak boleh dipakai sebagai data eksperimen.

## 1. Tata letak

```text
data/real/<session_id>/
  raw.csv         sampel mentah, ditulis HP A
  meta.json       identitas sesi
  labels.csv      interval label dari pengamat
data/synthetic/<session_id>/   struktur sama, data_kind=synthetic
data/processed/<dataset_id>/
  windows.csv     fitur berlabel
  raw_labeled.csv data mentah dengan label
  manifest.json   daftar sesi dan hash file sumber, versi skema, parameter jendela
  quality_report.md, quality_report.json
  quarantine.csv  jika ada baris dikarantina
  splits/<versi>/train.csv, validation.csv, test.csv
data/manifests/split_<dataset>_<versi>.json
```

Format `session_id`: `<tanggal>_<machine_id>_<phone>_<nomor>`, misalnya `20261105_M1_HPA_01`.

## 2. `raw.csv`

| Kolom | Tipe | Satuan | Wajib | Aturan |
|---|---|---|---|---|
| `session_id` | teks | - | Ya | Sama dengan nama folder |
| `seq` | int | - | Ya | Naik 1 |
| `t_mono_s` | float | detik | Ya | Tidak menurun |
| `t_epoch_ms` | int | ms | Ya | Jam HP A |
| `ax`, `ay`, `az` | float | m/s² | Ya | Finite |
| `gx`, `gy`, `gz` | float | rad/s | Ya | Finite |
| `dt_s` | float | detik | Baris pertama kosong | Interval aktual dari baris sebelumnya |
| `accel_fresh`, `gyro_fresh` | 0/1 | - | Ya | 0 berarti nilai terakhir dipakai ulang |
| `valid` | 0/1 | - | Ya | 0 jika tidak segar atau tidak finite |

```csv
session_id,seq,t_mono_s,t_epoch_ms,dt_s,ax,ay,az,gx,gy,gz,accel_fresh,gyro_fresh,valid
20261105_M1_HPA_01,0,1000.000000,1793750400000,,0.120000,-0.030000,9.790000,0.010000,0.000000,-0.010000,1,1,1
20261105_M1_HPA_01,1,1000.610000,1793750400610,0.610000,0.080000,0.050000,9.830000,0.010000,0.010000,0.000000,1,0,0
```

## 3. `meta.json`

```json
{
  "schema_version": 2,
  "source": "android",
  "units": {"accel": "m/s^2", "gyro": "rad/s"},
  "status": "complete",
  "session_id": "20261105_M1_HPA_01",
  "cycle_id": "M1_C01",
  "session_type": "cycle",
  "data_kind": "real",
  "device_id": "edge1",
  "phone_model": "contoh",
  "machine_id": "M1",
  "machine_type": "top_load",
  "program": "normal",
  "placement": "atas_tutup_tengah",
  "orientation": "layar_atas",
  "operator": "A1",
  "samples_per_window": 5,
  "interval_s": 0.1,
  "clock_offset_ms": 0,
  "notes": ""
}
```

Nilai `session_type`: `cycle`, `idle`, `disturbance`, `segment`, `measurement`. Perekam juga menambah `n_rows`, `n_invalid`, `n_stale`, `started_ms`, `ended_ms`, dan `sensor_fault_seen`. Untuk sesi selain `cycle`, `cycle_id` bernilai `null`.

## 4. `labels.csv`

| Kolom | Tipe | Aturan |
|---|---|---|
| `session_id` | teks | Sama dengan folder |
| `start_ms`, `end_ms` | int | Waktu pengamat, `start_ms` < `end_ms`, tidak tumpang tindih |
| `label` | teks | `IDLE`, `WASHING`, `SPIN`, `UNCERTAIN` |
| `phase_note` | teks, opsional | Misalnya `fill`, `soak`, `rinse`, `sync_tap` |
| `observer`, `method` | teks | Kode pengamat; `direct` atau `video` |

```csv
session_id,start_ms,end_ms,label,phase_note,observer,method
20261105_M1_HPA_01,1793750400000,1793750410000,UNCERTAIN,sync_tap,A1,direct
20261105_M1_HPA_01,1793750410000,1793750500000,IDLE,,A1,direct
20261105_M1_HPA_01,1793750500000,1793751100000,WASHING,,A1,direct
```

Waktu label dikoreksi ke jam HP A dengan `clock_offset_ms`, yang dihitung dari ketukan sinkron.

### Definisi label

| Label | Pakai saat | Jangan |
|---|---|---|
| `IDLE` | Motor dan tabung tidak bergerak, termasuk jeda | Menebak bagian yang tidak diamati |
| `WASHING` | Tabung atau pulsator mencuci atau membilas | Menandai seluruh siklus sebagai WASHING |
| `SPIN` | Tabung berputar cepat memeras | Menebak dari timer tanpa melihat atau mendengar |
| `UNCERTAIN` | Ragu, tidak melihat, HP tersentuh, atau ketukan sinkron | Menghapus intervalnya |

Saat air mengisi tanpa gerakan tabung, gunakan `IDLE` dengan `phase_note=fill`.

## 5. `windows.csv`

Satu baris adalah satu jendela agregat yang berakhir pada satu jendela edge.

| Kolom | Keterangan |
|---|---|
| `dataset_id`, `session_id`, `session_type`, `cycle_id`, `machine_id`, `device_id`, `data_kind` | Identitas. **Bukan fitur** |
| `window_start_ms`, `window_end_ms` | Rentang jendela agregat. **Bukan fitur** |
| `n_edge_windows`, `coverage_s`, `median_hz`, `stale_ratio` | Kualitas. **Bukan fitur** |
| `<base>_mean`, `<base>_std`, `<base>_max` | Fitur. `base` pada bagian 6 |
| `label` | `IDLE`, `WASHING`, atau `SPIN` |

Baris hanya dibuat jika seluruh jendela edge di dalamnya memiliki label yang sama, tidak berada dalam ±10 detik dari perubahan label (diusulkan), dan bukan `UNCERTAIN`.

Contoh di bawah adalah **keluaran nyata generator SINTETIS**, bukan pengukuran mesin cuci:

```csv
dataset_id,session_id,session_type,cycle_id,machine_id,device_id,data_kind,window_start_ms,window_end_ms,n_edge_windows,coverage_s,median_hz,stale_ratio,motion_rms_mean,motion_rms_std,motion_rms_max,rotation_rad_mean,rotation_rad_std,rotation_rad_max,acc_dyn_rms_mean,acc_dyn_rms_std,acc_dyn_rms_max,acc_mag_ptp_mean,acc_mag_ptp_std,acc_mag_ptp_max,gyro_rms_mean,gyro_rms_std,gyro_rms_max,gyro_max_mean,gyro_max_std,gyro_max_max,label
syn_v1,SYNTHETIC_IDLE_01,idle,,SYNM1,edge1,synthetic,1790057612477,1790057643481,10,31.003,1.5827,0.06,0.05013,0.01189,0.0752,0.03619,0.00609,0.0444,0.038233,0.005821,0.049601,0.06364,0.022328,0.109026,0.015879,0.002578,0.01945,0.02317,0.005014,0.030841,IDLE
```

## 5b. `raw_labeled.csv`

Gabungan data mentah dan label untuk diperiksa manusia: `session_id`, `device_id`, `machine_id`, `seq`, `t_epoch_ms`, `dt_s`, `label`, `ax` sampai `gz`, `accel_fresh`, `gyro_fresh`, `valid`. Nilai `label` mencakup `UNCERTAIN` dan `UNLABELED`. `raw.csv` sendiri tidak diubah setelah direkam.

## 6. Fitur

| Fitur dasar | Definisi | Satuan | Set |
|---|---|---|---|
| `motion_rms` | RMS dari `|a|-9.81` | m/s² | F1, F3 |
| `rotation_rad` | Σ `|ω|·Δt` | rad | F1, F3 |
| `acc_dyn_rms` | √(var(ax)+var(ay)+var(az)) | m/s² | F2, F3 |
| `acc_mag_ptp` | maks `|a|` dikurangi min `|a|` | m/s² | F2, F3 |
| `gyro_rms` | √(rata-rata `|ω|²`) | rad/s | F2, F3 |
| `gyro_max` | maks `|ω|` | rad/s | F2, F3 |

Varians memakai varians populasi. Fitur frekuensi hanya ditambah setelah gerbang G1.

`rotation_rad` bergantung pada durasi jendela, sehingga hanya dipakai pada F1 sebagai pembanding telemetri lama.

## 7. Aturan validasi

Lihat `docs/data_quality_rules.md`.

## 8. `split_<versi>.json`

```json
{
  "version": "v1",
  "dataset_id": "real_v1",
  "data_kind": "real",
  "windows_sha256": "hex",
  "seed": 42,
  "group_rule": "cycle_id jika ada, selain itu session_id",
  "holdout_machine": null,
  "train": ["M1_C01"],
  "validation": ["M1_C02"],
  "test": ["M1_C07", "M1_C08"],
  "cv_folds_leave_one_cycle_out": [{"validation": ["M1_C01"], "train": ["M1_C02"]}],
  "n_windows_per_label": {"train": {"IDLE": 0}},
  "machines": ["M1"],
  "evaluation_ready": false,
  "warnings": ["contoh"]
}
```

## 9. Metadata model (direncanakan untuk Phase 5)

```json
{
  "model_name": "washalert_activity",
  "model_version": "0.1.0+contoh",
  "algorithm": "contoh",
  "hyperparameters": {},
  "feature_schema_version": 1,
  "feature_names": ["acc_dyn_rms_mean"],
  "classes": ["IDLE", "SPIN", "WASHING"],
  "window": {"edge_samples": 5, "aggregate_s": 30, "min_windows": 3, "min_coverage_s": 20},
  "probability_threshold": 0.6,
  "smoothing_n": 5,
  "dataset_manifest_hash": "hex",
  "data_kind": "synthetic",
  "seed": 42,
  "versions": {"python": "x", "scikit_learn": "x", "numpy": "x", "joblib": "x"},
  "sha256": "hex",
  "created_at": "tanggal"
}
```

Laporan evaluasi disimpan terpisah di `reports/`, sehingga metadata model tidak membawa klaim performa.
