# Laporan Phase 7: Dashboard dan Pengalaman Pengguna

Tanggal 5 November 2026. Pengujian memakai Chromium dan broker lokal di lingkungan cloud. Belum ada pengujian pada HP sungguhan, mesin cuci, atau HiveMQ.

## 1. Ringkasan

Dashboard baru sudah berjalan dan terhubung ke detector nyata. Status, aktivitas, model, alert, dan hasil konfirmasi semuanya berasal dari pesan MQTT, dan ARM/DISARM baru dinyatakan berhasil setelah detector menjawab. Tiga fitur opsional tidak dibuat karena backend atau SRS tidak mendukungnya (bagian 6).

| Tingkat bukti | Status |
|---|---|
| Implemented | Sudah |
| Automated test | 380 test lulus, 32 di antaranya di Chromium |
| Browser test | Sudah, Chromium termasuk emulasi 360 piksel |
| Simulation test | Sudah, demo 43/43 pemeriksaan |
| Hardware test | **Belum** |

## 2. Sebelum dan sesudah

| Aspek | Sebelum | Sesudah |
|---|---|---|
| Sebelum ada data | Menampilkan `0 menit` dan `0.000` | Teks "Belum ada siklus", "Menunggu data sensor" |
| ARM/DISARM | Terkirim tanpa umpan balik | Mengirim, dikonfirmasi detector, batas waktu 8 detik, atau gagal |
| DISARM | Langsung mereset siklus | Minta konfirmasi dulu |
| Grafik | RMS saja, sumbu indeks, garis menutup celah | RMS dan rotasi, sumbu waktu, celah diputus dan ditandai, tooltip |
| Model | Satu baris teks | Panel model, banner sintetis, alasan fallback |
| Alert | Tidak tampil | Aktif, penjelasan, pengingat, konfirmasi, riwayat |
| Data usang | Tidak terlihat | Live, usang, offline per perangkat |
| Linimasa | Tidak ada | Status siklus, aktivitas, dan sumber aktivitas sejajar |
| Validasi | Hanya parse JSON | Skema, dedupe, sequence, CSP |
| Pustaka | CDN unpkg | Tersimpan lokal |

## 3. Arsitektur dan integrasi

Lihat `dashboard_design.md`. MQTT over WebSocket dan `dashboard_server.py` dipertahankan. Tidak ada framework atau langkah build.

## 4. File

| File | Perubahan |
|---|---|
| `dashboard/index.html` | Ditulis ulang. Judul halaman dipertahankan agar test lama tetap utuh |
| `dashboard/assets/css/dashboard.css`, `assets/js/store.js`, `charts.js`, `app.js` | Baru |
| `dashboard/assets/vendor/` | MQTT.js 5.10.1 (versi sama), font Atkinson Hyperlegible Next |
| `nodes/detector_service/main.py` | `last_command`, `ended_by` |
| `shared/edge_runner.py` | `data_source` pada telemetri |
| `shared/dashboard_server.py` | Batas usang dan offline, `DASHBOARD_HOST`, header keamanan |
| `scripts/e2e_demo.py` | Pemeriksaan dashboard dan screenshot, opsi `--browser` menggantikan `--mqtt-js` |
| `tests/test_dashboard_ui.py`, `test_dashboard_contract.py` | Baru |
| `docs/dashboard_design.md`, `dashboard_user_guide.md`, `phase7_report.md` | Baru |
| SRS, RTM, SDD, change log, README, `.env.example`, `requirements-dev.txt` | Diperbarui |

## 5. Hasil pengujian

**Regresi:** `WASHALERT_SLOW=1 python -m unittest discover -s tests -t .` menjalankan 380 test dan semuanya lulus (317 detik). Sebelum Phase 7 ada 339 test. Empat file test asli identik dengan baseline, dan `scripts.offline_demo` berjalan.

**Browser, 20 kasus yang diminta** (`tests/test_dashboard_ui.py`, Chromium, MQTT sungguhan lewat broker lokal, tanpa galat JavaScript atau CSP):

| No | Kasus | Hasil |
|---|---|---|
| 1, 2 | Halaman termuat, keadaan awal tanpa nilai palsu | Lulus |
| 3, 5 | Telemetri valid, grafik berubah | Lulus |
| 4 | Telemetri tidak valid diabaikan dan dihitung | Lulus |
| 6 | Prediksi tampil tanpa label confidence | Lulus |
| 7 | Status model tidak dikenal | Lulus |
| 8, 9 | RULE_ONLY, HYBRID, fallback | Lulus |
| 10 | Penanda sintetis dan simulasi | Lulus |
| 11, 12 | Broker putus dan tersambung lagi | Lulus |
| 13 | Data usang lalu offline | Lulus |
| 14, 15 | Alert diterima dan dikonfirmasi | Lulus (kasus 15 memakai payload buatan; dengan HP B simulator di demo) |
| 16, 17 | ARM dan DISARM dengan detector nyata | Lulus |
| 18 | Batas waktu perintah, gagal saat terputus | Lulus |
| 19 | Pesan duplikat | Lulus |
| 20 | Lebar 360, 768, 1280 tanpa scroll horizontal, tombol ≥ 44 piksel | Lulus |

Tambahan: celah grafik, markup dalam payload tampil sebagai teks, form login, keyboard, reduced motion, batas buffer, OFFLINE dari Last Will. Form login hanya diuji dengan pustaka MQTT tiruan.

**Skenario E2E (SIMULATION).** `detector.py`, `hp_pemilik.py --source simulator`, model sintetis, rekaman sintetis C05 sebagai pengganti HP A, broker lokal. Hasil 43/43. Bukti: `reports/e2e/phase7/`.

| Skenario | Hasil | Screenshot |
|---|---|---|
| A IDLE | Lulus | `a_idle.png` |
| B WASHING, grafik berubah | Lulus, dengan catatan di bawah | `b_washing.png` |
| C model mengidentifikasi SPIN | Lulus | `c_spin.png` |
| D jeda tanpa DONE | Lulus | `d_pause.png` |
| E selesai dan alert | Lulus | `e_done_alert.png` |
| F konfirmasi HP B | Lulus, goyangan dikirim script | `f_ack.png` |
| G broker putus | Lulus | `g_broker_down.png` |
| H model rusak, fallback | Lulus | `h_fallback.png` |
| I ARM/DISARM dengan balasan detector | Lulus | `i_disarm.png` |
| J lebar ponsel | Lulus, emulasi Chromium | `j_mobile.png` |

**Putaran pertama yang perlu diketahui.** Putaran pertama lulus 39/43. Satu kegagalan muncul karena pemeriksaan mengharuskan layar menampilkan WASHING, padahal detector saat itu melaporkan SPIN. Tiga lainnya berasal dari script: goyangan buatan terselip data diam dari `hp_pemilik.py` simulator, sehingga dua jendela goyang tidak berurutan. Script diperbaiki dengan mengulang goyangan.

**Catatan model.** Pada skenario B, dari 35 status saat diberi data berlabel WASHING, 24 berstatus SPIN, 5 WASHING, dan 6 IDLE. Dashboard menampilkannya dengan benar, tetapi ini menunjukkan model sintetis salah kelas. Urutan tercatat pun bolak-balik antara WASHING dan SPIN. Hasil ini sebaiknya tidak dipakai sebagai contoh klasifikasi yang baik saat presentasi.

**Pengukuran**, laptop cloud dengan broker lokal, 453 detik: inference median 0,56 ms, telemetri sampai status median 4,2 ms dan p95 6,4 ms, alert 3,1 dan 4,7 ms, CPU detector 0,5% satu core, memori puncak 156 MB. Ukuran aset: HTML, CSS, dan JS sekitar 61 KB, MQTT.js 330 KB, font 34 KB. Waktu muat halaman dan memori browser tidak diukur.

## 6. Status fitur yang diminta tetapi tidak dibuat

| Fitur | Status | Alasan |
|---|---|---|
| Memilih mode dari dashboard | BLOCKED | Mode hanya berubah lewat restart (Phase 6). Mode ditampilkan saja |
| Konfirmasi alert dari dashboard | Tidak dibuat | SRS menetapkan konfirmasi lewat goyangan HP B. Dashboard menampilkan hasilnya |
| Uji notifikasi | BLOCKED | Backend tidak punya perintahnya |
| Riwayat persisten | BLOCKED | Backend tidak menyimpan riwayat. Riwayat hanya di memori tab dan dinyatakan begitu |
| Status OFFLINE HP dari Last Will | BLOCKED | Edge belum memasang Last Will, jadi keadaan HP disimpulkan dari waktu data terakhir |
| Unauthorized | Sebagian | Pesan ditangani, tetapi belum diuji dengan broker berakun nyata |

Jika kelompok ingin dua pilihan pertama, keduanya butuh perubahan protokol lewat CR, dan perlu broker berakun agar aman.

## 7. Masalah yang diketahui

1. Batas usang 20 detik dan offline 60 detik masih usulan. Periode telemetri HP nyata belum terukur, sehingga HP A bisa keliru tampak usang.
2. Pada broker publik, status palsu tampil apa adanya.
3. Kedaluwarsa alert memakai jam browser dan jam detector.
4. Buffer grafik 1.200 titik. Rentang 15 menit terpotong jika telemetri lebih cepat dari sekitar 1,3 pesan per detik.
5. Probabilitas yang tampil berasal dari prediksi mentah, sedangkan aktivitas sudah melalui smoothing, sehingga keduanya bisa berbeda.
6. Tema gelap sudah dibuat, tetapi tampilannya belum diperiksa.
7. NFR-020 (uji pemahaman oleh anggota lain) belum dilakukan dan butuh orang sungguhan.
8. Demo ulang menghapus artefak `reports/e2e/C04` dan `C05` Phase 6 dari repo. Salinannya ada di `WashAlert-AI_phase6.zip`, dan angkanya tercatat di `phase6_report.md`.
9. Dashboard bawaan hanya bisa dibuka dari laptop. Pembukaan di HP lewat `DASHBOARD_HOST` belum diuji, dan halaman itu tidak punya login.

## 8. Traceability

RTM v0.6: 143 kebutuhan. Existing and verified 24, Existing but not verified 11, Planned 13, Implemented but not tested 12, Implemented and tested 83. FR-071 kini terverifikasi, dan FR-074 sampai FR-078 serta NFR-021 teruji. NFR-011 masih sebagian dan NFR-020 masih direncanakan. CR-011 berstatus diusulkan dan perlu disetujui kelompok.

## 9. Cara menjalankan

```bash
python detector.py     # dashboard di http://localhost:8000
python -m unittest tests.test_dashboard_ui
python -m scripts.e2e_demo --model models/development/SYNTHETIC_... --browser --out reports/e2e/phase7
```

## 10. Kesiapan Phase 8

| Item | Status |
|---|---|
| Test otomatis dan browser berjalan | Siap |
| Demo A sampai J dengan bukti | Siap, simulasi |
| Uji dashboard di browser HP nyata dan lewat HiveMQ | Belum |
| Telemetri nyata untuk menetapkan batas usang | Belum |
| Uji pemahaman NFR-020 | Belum |
| Dataset nyata dan perbandingan empat kelompok | Belum, menjadi syarat klaim peningkatan |
