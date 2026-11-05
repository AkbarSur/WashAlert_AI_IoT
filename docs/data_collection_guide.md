# Panduan Pengumpulan Data: WashAlert AI

Panduan ini ditujukan untuk anggota kelompok yang merekam di lapangan. Kebutuhan terkait ada di SRS bagian 3.4 dan 6.

> **Status:** alat sudah tersedia dan diuji dengan `termux-sensor` tiruan. **Belum pernah dijalankan di HP sungguhan.** Sesi pertama sekaligus menjadi uji alat.

## 1. Persiapan satu kali

Di HP A, dari folder proyek:

```bash
pkg install python termux-api
pip install -r requirements.txt
termux-sensor -l
```

Pastikan accelerometer dan gyroscope muncul.

**Ukur HP, lalu kirim hasilnya ke kelompok** (HP diam di meja):

```bash
python -m ml.measure_sampling --phone hpA --duration 120
```

Hasil tersimpan di `reports/sampling_hpA.json`. Periksa:

| Nilai | Arti | Jika bermasalah |
|---|---|---|
| `rate_median_hz` | Laju nyata per panggilan | Dipakai untuk memutuskan panjang jendela (gerbang G1) |
| `gyro_empty_pct` | Pembacaan gyro kosong | Jika tinggi, periksa izin Termux:API dan `SENSOR_GYRO` |
| `rest_offset_mps2` | Selisih magnitude dari 9,81 saat diam | Dicatat. Fitur baru tidak terpengaruh |
| `unit_check` | Pemeriksaan satuan | Jika bukan "wajar", hentikan dan laporkan |
| `stream_probe` | Laju satu panggilan panjang | Dipakai untuk memilih metode akuisisi |

## 2. Aturan penamaan

| Hal | Contoh | Aturan |
|---|---|---|
| `--session` | `20261105_M1_HPA_01` | Unik, tanggal_mesin_HP_nomor |
| `--cycle-id` | `M1_C01` | Satu siklus cuci, unik |
| `--machine-id` | `M1` | Pseudonim, tanpa alamat atau nama pemilik |
| `--operator`, `--observer` | `A1` | Kode anggota, bukan nama |
| `--placement` | `atas_tutup_tengah` | Sama untuk semua sesi pada posisi yang sama |
| `--orientation` | `layar_atas` | Arah HP |

Foto posisi HP disimpan di luar repository. Tandai posisi dengan selotip agar dapat diulang.

## 3. Merekam satu siklus penuh

Butuh dua orang atau dua perangkat: **HP A di mesin dan tidak disentuh, pengamat memakai HP B atau laptop.**

1. Letakkan HP A pada posisi bertanda, lalu sambungkan ke pengisi daya bila bisa.
2. Di HP A: `termux-wake-lock`, lalu jalankan:

   ```bash
   python -m ml.record_session --session 20261105_M1_HPA_01 --session-type cycle \
     --cycle-id M1_C01 --machine-id M1 --machine-type top_load --program normal \
     --phone-model hpA --placement atas_tutup_tengah --orientation layar_atas --operator A1
   ```

3. Di perangkat pengamat:

   ```bash
   python -m ml.label_session --session 20261105_M1_HPA_01 --observer A2
   ```

4. Sinkronkan waktu: ketik `y`, Enter, lalu segera ketuk badan mesin tiga kali dengan kuat. Lalu ketik `i`, Enter.
5. Biarkan minimal 2 menit dalam IDLE, lalu mulai mesin.
6. Ikuti `docs/labeling_protocol.md`. Setiap fase berubah: ketik `i`, `w`, `s`, atau `u`, lalu Enter.
7. Setelah mesin berhenti, biarkan IDLE 5 menit. Ketik `q` pada alat label, dan Ctrl+C pada perekam.
8. Salin `labels.csv` dan folder sesi ke laptop, ke `data/real/<session>/`. Lalu:

   ```bash
   python -m ml.label_session --session 20261105_M1_HPA_01 --compute-offset
   python -m ml.validate_dataset --root data/real
   ```

Jika `--compute-offset` tidak menemukan ketukan, itu wajar pada sampling lambat. Offset tetap 0. Pastikan jam kedua perangkat memakai waktu jaringan, dan catat di `--notes` jika selisihnya terlihat.

Alternatif: rekam mesin dengan video, buat `events.csv` (`video_s,label,phase_note`, baris terakhir `END`), lalu gunakan `--from-events events.csv --video-start-ms <epoch>`.

## 4. Sesi pendukung

Sesi satu kondisi yang diamati langsung dapat memakai `--label`:

```bash
# Mesin mati, HP A pada posisi biasa
python -m ml.record_session --session 20261105_M1_HPA_I01 --session-type idle --machine-id M1 \
  --machine-type top_load --phone-model hpA --placement atas_tutup_tengah --orientation layar_atas \
  --operator A1 --duration 600 --label IDLE --observer A1
```

| Sesi | `--session-type` | Yang dilakukan | Label |
|---|---|---|---|
| Mesin mati | `idle` | Rekam 10 menit pada beberapa waktu | `IDLE` |
| Mesin tetangga berjalan | `disturbance` | Mesin kita mati, mesin lain aktif | `IDLE`, catat di `--notes` |
| Pintu dibanting, langkah kaki | `disturbance` | Lakukan beberapa kali, HP tidak disentuh | `IDLE` |
| HP tersenggol | `disturbance` | Gunakan alat label, tandai `u` saat disenggol | `UNCERTAIN` untuk momen itu |
| Posisi HP berbeda | `cycle` | Siklus penuh pada posisi lain | Sesuai fase |

Target awal yang diusulkan: 8 siklus penuh dan 3 sesi pendukung. Jadwalkan sejak awal: satu siklus tidak dapat dipercepat.

## 5. Daftar periksa setiap sesi

- [ ] Layar tidak dimatikan paksa, wake lock aktif, baterai cukup.
- [ ] Notifikasi dan getar HP A dimatikan. Getar HP sendiri ikut terekam.
- [ ] HP A stabil dan tidak disentuh.
- [ ] `--session` belum pernah dipakai.
- [ ] Pengamat melihat atau mendengar mesin selama sesi.
- [ ] Setelah selesai: validator tidak menolak sesi.
- [ ] Temuan tidak biasa ditulis di `--notes`, atau label `u`.

## 6. Masalah umum

| Gejala | Tindakan |
|---|---|
| `termux-sensor is missing` | Pasang Termux:API dari F-Droid dan `pkg install termux-api` |
| Sensor tidak terdeteksi | Atur `SENSOR_ACCEL` dan `SENSOR_GYRO` di `.env` |
| `sensor tidak memberi nilai baru` | Jalankan `termux-sensor -c`. Sesi tetap tersimpan, periksa validator |
| Rekaman berhenti saat layar mati | Wake lock, nonaktifkan optimasi baterai untuk Termux. Sesi berstatus `interrupted` tetap dapat divalidasi |
| `Sesi sudah ada` | Gunakan nomor sesi baru. File lama tidak ditimpa |
| Sesi ditolak V14 | Satuan tampak salah. Laporkan, jangan mengubah data |

Setelah semua sesi tervalidasi:

```bash
python -m ml.build_dataset --root data/real --dataset-id real_v1
python -m ml.split_dataset --dataset real_v1 --version v1
```
