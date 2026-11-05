# Spesifikasi Fitur: WashAlert AI

Definisi tunggal ada di `shared/features.py`. Kode ini dipakai edge dan `ml.build_dataset`, dan inference. Test `test_dataset_and_runtime_paths_match` memastikan hasilnya sama.

## 1. Jendela

| Tingkat | Definisi | Nilai saat ini | Status |
|---|---|---|---|
| Jendela edge | N sampel berurutan tanpa tumpang tindih, berdasarkan `seq // N` | N = 5, sama dengan edge lama | Lama |
| Jendela agregat | Jendela edge yang berakhir dalam 30 detik terakhir, bergeser tiap telemetri | 30 dtk, minimal 3 jendela, cakupan ≥ 20 dtk | Diusulkan, final setelah G1 |

Jendela agregat hanya memakai jendela yang sudah selesai, sehingga tidak ada informasi masa depan.

**Durasi jendela edge tidak tetap.** Durasinya bergantung pada laju HP, sehingga `window_s` dicatat dan fitur baru dibuat tidak bergantung pada durasi.

## 2. Fitur jendela edge

`a` adalah vektor accelerometer dalam m/s², dan `ω` adalah vektor gyroscope dalam rad/s.

| Fitur | Rumus | Satuan | Kegunaan | Data tidak valid |
|---|---|---|---|---|
| `motion_rms` | √(rata-rata (`|a|`−9,81)²) | m/s² | Fitur lama, jalur aturan. Peka offset dan lemah pada arah horizontal | Jendela tidak terbit |
| `rotation_rad` | Σ `|ω|`·Δt, Δt negatif menjadi 0 | rad | Fitur lama. Bergantung durasi | Jendela tidak terbit |
| `acc_dyn_rms` | √(var(ax)+var(ay)+var(az)), varians populasi | m/s² | Kekuatan getaran semua arah, offset gravitasi hilang | Jendela tidak terbit |
| `acc_mag_ptp` | maks `|a|` − min `|a|` | m/s² | Puncak perubahan, peka hentakan | Jendela tidak terbit |
| `gyro_rms` | √(rata-rata `|ω|²`) | rad/s | Goyangan, tidak bergantung durasi | Jendela tidak terbit |
| `gyro_max` | maks `|ω|` | rad/s | Goyangan puncak | Jendela tidak terbit |
| `window_s` | t terakhir − t pertama | detik | Kualitas | Mundur menjadi 0, jendela tidak dipakai |
| `n_samples` | Jumlah sampel | - | Kualitas | Minimal 2 |
| `actual_hz` | (n−1)/`window_s` | Hz | Laju nyata | 0 jika `window_s` 0 |
| `stale_count` | Sampel dengan sensor tidak segar | - | Kualitas | Jika lebih dari 40%, jendela tidak dipakai |

`motion_rms` dan `rotation_rad` tidak berubah maknanya, dan masih dihitung oleh `extract_features` lama.

## 3. Fitur model

Setiap fitur dasar diringkas dalam jendela agregat: `_mean`, `_std` (deviasi standar populasi), dan `_max`.

| Set | Fitur dasar | Jumlah kolom | Pertanyaan pada Phase 5 |
|---|---|---:|---|
| F1 | `motion_rms`, `rotation_rad` | 6 | Seberapa jauh telemetri lama dapat digunakan? |
| F2 | `acc_dyn_rms`, `acc_mag_ptp`, `gyro_rms`, `gyro_max` | 12 | Apakah fitur baru cukup? Set ini kandidat utama |
| F3 | F1 + F2 | 18 | Apakah gabungan menambah sesuatu? |

Urutan diberikan oleh `feature_names()`.

## 4. Yang sengaja tidak ditambahkan

| Fitur | Alasan |
|---|---|
| Varians | Hanya kuadrat dari SD, tanpa informasi tambahan untuk model pohon |
| Min accel | Tergantung orientasi dan gravitasi. Rentang sudah terwakili `acc_mag_ptp` |
| FFT, frekuensi dominan | Laju nyata belum diketahui. Pada laju rendah hasilnya terkena aliasing |
| `session_id`, `machine_id`, waktu, urutan fase, status FSM | Membocorkan label atau identitas |

## 5. Yang belum terbukti

Fitur baru telah diuji pada sinyal buatan dengan hasil yang diketahui. Kemampuannya membedakan kelas pada mesin nyata belum diketahui. Dengan 5 sampel per jendela, SD dan rentang per jendela bersifat noisy, dan karena itu model memakai statistik agregat.
