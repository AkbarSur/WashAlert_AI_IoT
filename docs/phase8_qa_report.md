# Laporan QA Phase 8

Tanggal 5 November 2026. Lingkungan: container Linux cloud, Python 3.13, broker lokal amqtt, Chromium lewat Playwright. **HP, mesin cuci, Windows, dan HiveMQ tidak tersedia.**

## 1. Kesimpulan

Perangkat lunak lulus semua pengujian yang dapat dijalankan di lingkungan ini. Status **belum final untuk klaim dunia nyata**: pengujian HP, TLS ke HiveMQ, dan dataset nyata belum dilakukan.

| Tingkat bukti | Status |
|---|---|
| Unit dan integrasi | Lulus |
| Browser | Lulus |
| Simulasi end-to-end | Lulus |
| Uji ketahanan simulator | Lulus |
| Instalasi bersih | Lulus |
| HP nyata | **Belum** |
| Mesin cuci nyata | **Belum** |

## 2. Hasil

| Pengujian | Perintah | Hasil |
|---|---|---|
| Seluruh test | `WASHALERT_SLOW=1 python -m unittest discover -s tests -t .` | 386 test lulus, 0 dilewati, 324 detik |
| Instalasi bersih | Hanya file yang akan dilacak Git, venv baru, `requirements.txt`, `requirements-ml.txt`, amqtt, tanpa Playwright | 380 test, 34 dilewati, tidak ada yang gagal (versi sebelum 6 test paket akhir ditambahkan) |
| Reproduksibilitas | Generator, dataset, dan training diulang dari salinan bersih | `model.joblib` identik byte per byte, hash dataset cocok dengan split terkunci |
| Demo A sampai J | `python -m scripts.e2e_demo --browser` | 43/43. Putaran sebelumnya 39/43, lihat `phase7_report.md` |
| Uji ketahanan | `python -m scripts.soak_test --minutes 60`, mode HYBRID sintetis | 60 menit tanpa crash, 0 traceback, 0 galat handler |
| Broker lokal sesuai README | `demo/env.lokal.example`, tiga proses simulator | Alert, alarm HP B, konfirmasi, dan notifikasi dihapus berjalan |
| Regresi | 4 file test asli | Identik dengan baseline dan lulus |
| Dokumen | `check.py` internal dan `test_release_consistency` | ID konsisten, 9 diagram SRS ter-render, tautan valid |

**Uji ketahanan.** Memori detector rata-rata 154,8 MB pada sepertiga awal dan 155,0 MB pada sepertiga akhir. CPU 0,23% satu core. 5.130 telemetri diproses dan 178 alert terkirim. Jumlah alert itu wajar karena HP B simulator tidak mengonfirmasi, sehingga pengingat 20 detik berulang setelah satu siklus. Skenario ini hanya memuat satu siklus cuci dan tidak menguji broker putus; itu diuji test terpisah.

**Coverage.** Cabang dan baris 71% secara keseluruhan, diukur pada proses test saja.

| Modul | Coverage |
|---|---:|
| `activity.py`, `inference.py`, `processing.py`, `dashboard_server.py`, `metrics.py` | 100% |
| `rules.py` | 99% |
| `messages.py`, `features.py` | 98% |
| `sensors.py` | 84% |
| `main.py` | 78% |
| `edge_runner.py` | 48% |
| `mqtt_connection.py` | 29% |
| `figures.py` | 13% |

`edge_runner.py` dan `mqtt_connection.py` dijalankan sebagai subproses pada test broker, yang tidak terhitung, jadi angkanya lebih rendah dari cakupan sebenarnya. Grafik `figures.py` hanya dijalankan pada training manual.

**Keamanan.** Pemindaian file yang dilacak tidak menemukan kredensial, path lokal, atau alamat email. `.env` diabaikan Git. Lihat juga bagian 11 `phase6_report.md`.

**Tidak dapat diuji.** Percobaan menjangkau `broker.hivemq.com` gagal karena lingkungan tidak dapat me-resolve namanya, sehingga koneksi TLS nyata belum teruji.

## 3. Kepatuhan SRS

| Status | Semua (143) | Must (113) |
|---|---:|---:|
| Implemented and tested | 86 | 69 |
| Existing and verified | 25 | 24 |
| Implemented but not tested | 12 | 8 |
| Existing but not verified | 10 | 9 |
| Planned | 10 | 3 |

"Implemented and tested" berarti perangkat lunak, memakai simulator, tiruan, atau broker lokal.

## 4. Kebutuhan yang belum terpenuhi atau belum terbukti

| Kebutuhan | Status | Butuh |
|---|---|---|
| FR-001 Pembacaan sensor, FR-058 Alarm HP B | Kode ada, belum diverifikasi di HP pada versi ini | HP |
| FR-006 Alat ukur sampling, DML-006 Protokol label | Belum di lapangan | HP dan pengamatan |
| FR-043 Toleransi offset, FR-049 Batas diam berbasis data, DML-009, DML-018, DML-020, DML-021, DML-024 | Mekanisme ada | Data nyata |
| **NFR-004, NFR-007, NFR-008** (Must): keterlambatan, alert palsu, alert terlewat | **Belum terbukti.** Pada 2 siklus sintetis, HYBRID melewatkan 1 | Siklus nyata |
| NFR-003 Latensi notifikasi | Belum sampai alarm HP | HP |
| NFR-010 TLS | Kode bawaan, belum diuji ke HiveMQ pada versi ini | Internet |
| NFR-011 Broker berakun | Sebagian | Broker berakun |
| NFR-020 Pemahaman dashboard | Belum | Anggota lain |
| NFR-022 Panduan penyiapan | README ada, belum dicoba orang lain | Anggota lain |
| NFR-024 Windows | Belum dijalankan | Laptop Windows |
| FR-007, FR-014, NFR-019, NFR-026, DML-005 | Belum dikerjakan | Should atau Could, kecuali DML-005 yang bersyarat |

## 5. Masalah terbuka

| Tingkat | Masalah | Dampak | Tindakan |
|---|---|---|---|
| Tinggi | Tidak ada data nyata | Akurasi tidak diketahui | Rekam siklus |
| Tinggi | Model sintetis melewatkan penyelesaian, dan salah kelas WASHING menjadi SPIN | Bukan model layak pakai | Latih ulang dengan data nyata. Tetap `RULE_ONLY` sampai ada bukti |
| Tinggi | Broker publik dapat dipalsukan | Alert atau DISARM palsu | Broker berakun |
| Sedang | Satu jendela non-IDLE mereset timer diam | DONE dapat tertunda | Putuskan dengan data nyata |
| Sedang | CR-006 belum diputuskan | Status dapat tertahan di WASHING | Keputusan kelompok |
| Sedang | Batas waktu dan ambang masih usulan | Perilaku nyata belum diketahui | Ukur |
| Rendah | `LICENSE` memuat nama "PocketGuard IoT contributors" | Atribusi | Keputusan pemilik |
| Rendah | Tema gelap belum diperiksa, riwayat tidak tersimpan | Tampilan dan riwayat | Periksa bila perlu |

## 6. Blocker

1. Akses HP dan mesin cuci, untuk pengujian fisik dan dataset.
2. Keputusan kelompok: CR-006, CR-009 sampai CR-012, lisensi, identitas tim.
3. Ketentuan dosen tertulis untuk bagian AI dan tenggat, yang sampai sekarang belum saya terima.

## 7. Cara mengulang

Lihat README bagian 20. Bukti: `reports/e2e/phase7/`, `reports/soak/`, `reports/arms/`.
