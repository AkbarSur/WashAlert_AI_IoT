# Matriks Keterlacakan SRS ke Desain: WashAlert AI

Versi 0.1, mengikuti SRS v0.2 dan SDD v0.1, 4 November 2026. Daftar komponen ada di SDD bagian 5.2.

Matriks ini menunjukkan rencana. Semua status tetap sama dengan RTM, karena belum ada implementasi.

## Beban per tahap

| Tahap | Must | Should | Could | Total |
|---|---|---|---|---|
| 1. Pengumpulan data | 2 | 3 | 1 | 6 |
| 2. Rekayasa fitur | 2 | 0 | 1 | 3 |
| 3. Training model | 6 | 0 | 0 | 6 |
| 4. Evaluasi model | 10 | 2 | 0 | 12 |
| 5. Integrasi model | 3 | 1 | 0 | 4 |
| 6. Hybrid ML + FSM | 4 | 3 | 0 | 7 |
| 7. Dashboard | 0 | 1 | 1 | 2 |
| 8. Pengujian | 82 | 20 | 1 | 103 |

## Matriks

| ID | Kebutuhan | Prioritas | Paket | Komponen | Bagian SDD | Tahap | Status | Butuh data nyata |
|---|---|---|---|---|---|---|---|---|
| FR-001 | Pembacaan accelerometer dan gyroscope | Must | Inti | C-01 | 4.3, 4.4, 7.5 | 8 | Existing but not verified | Ya |
| FR-002 | Deteksi nama sensor | Must | Inti | C-01 | 4.3, 4.4, 7.5 | 8 | Implemented and tested | Tidak |
| FR-003 | Penandaan sampel basi | Must | Inti | C-01, C-03 | 4.3, 4.4, 7.5 | 8 | Implemented and tested | Tidak |
| FR-004 | Deteksi sensor gagal | Must | Inti | C-01, C-06 | 4.3, 4.4, 7.5 | 8 | Implemented and tested | Tidak |
| FR-005 | Waktu dan laju nyata | Must | Inti | C-03 | 4.3, 4.4, 7.5 | 8 | Implemented and tested | Tidak |
| FR-006 | Alat ukur sampling | Must | Inti | C-17 | 4.3, 4.4, 7.5 | 8 | Implemented but not tested | Ya |
| FR-007 | Pemanfaatan semua sampel | Should | Tambahan | C-01 | 4.3, 4.4, 7.5 | 1 | Planned | Ya |
| FR-008 | Processing A: motion_rms | Must | Inti | C-02 | 4.4 | 8 | Existing and verified | Tidak |
| FR-009 | Processing B: rotation_rad | Must | Inti | C-02 | 4.4 | 8 | Existing and verified | Tidak |
| FR-010 | Fitur getaran tanpa offset | Must | Inti | C-03 | 4.4 | 8 | Implemented and tested | Tidak |
| FR-011 | Moving average | Must | Inti | C-08 | 4.4 | 8 | Existing and verified | Tidak |
| FR-012 | Timer durasi | Must | Inti | C-08 | 4.4 | 8 | Existing and verified | Tidak |
| FR-013 | Sampel tidak valid | Must | Inti | C-03, C-06 | 4.4 | 8 | Implemented and tested | Tidak |
| FR-014 | Fitur frekuensi bersyarat | Could | Opsional | C-03, C-23 | 4.4 | 2 | Planned | Ya |
| FR-015 | Publikasi telemetri | Must | Inti | C-06 | 7.2, 7.5 | 8 | Existing and verified | Tidak |
| FR-016 | Telemetri v2 kompatibel | Must | Inti | C-04 | 7.2, 7.5 | 2 | Implemented and tested | Tidak |
| FR-017 | Validasi skema | Must | Inti | C-04 | 7.2, 7.5 | 8 | Implemented and tested | Tidak |
| FR-018 | Kecocokan topik dan device | Must | Inti | C-11 | 7.2, 7.5 | 8 | Existing but not verified | Tidak |
| FR-019 | Penolakan pesan basi | Must | Inti | C-08 | 7.2, 7.5 | 8 | Existing and verified | Tidak |
| FR-020 | Penolakan replay | Must | Inti | C-08 | 7.2, 7.5 | 8 | Existing and verified | Tidak |
| FR-021 | Penolakan terlihat | Should | Tambahan | C-11 | 7.2, 7.5 | 6 | Implemented and tested | Tidak |
| FR-022 | Edge tahan putus koneksi | Must | Inti | C-06 | 7.2, 7.5 | 1 | Implemented and tested | Tidak |
| FR-023 | Retry koneksi awal | Should | Tambahan | C-05 | 7.2, 7.5 | 1 | Implemented and tested | Tidak |
| FR-024 | Perekaman sampel mentah | Must | Inti | C-18 | 4.1 sampai 4.3 | 8 | Implemented and tested | Ya |
| FR-025 | Identitas sesi | Must | Inti | C-18 | 4.1 sampai 4.3 | 8 | Implemented and tested | Tidak |
| FR-026 | Pelabelan observasi | Must | Inti | C-19 | 4.1 sampai 4.3 | 8 | Implemented and tested | Ya |
| FR-027 | Pencegahan rekaman tercampur | Must | Inti | C-18 | 4.1 sampai 4.3 | 8 | Implemented and tested | Tidak |
| FR-028 | Validator dataset | Must | Inti | C-20 | 4.1 sampai 4.3 | 8 | Implemented and tested | Tidak |
| FR-029 | Ekspor dataset jendela | Must | Inti | C-03, C-21 | 4.1 sampai 4.3 | 8 | Implemented and tested | Tidak |
| FR-030 | Pemisahan data sintetis | Must | Inti | C-20, C-22 | 4.1 sampai 4.3 | 8 | Implemented and tested | Tidak |
| FR-031 | Perintah training | Must | Inti | C-23 | 3.3, 3.4, 6.4 | 8 | Implemented and tested | Tidak |
| FR-032 | Perintah evaluasi | Must | Inti | C-24 | 3.3, 3.4, 6.4 | 4 | Implemented and tested | Tidak |
| FR-033 | Artefak model | Must | Inti | C-23 | 3.3, 3.4, 6.4 | 3 | Implemented and tested | Tidak |
| FR-034 | Pemuatan model aman | Must | Inti | C-10 | 3.5, 7.3 | 5 | Implemented and tested | Tidak |
| FR-035 | Prediksi aktivitas | Must | Inti | C-10 | 3.5, 7.3 | 8 | Implemented and tested | Tidak |
| FR-036 | Agregasi jendela | Must | Inti | C-09 | 3.5, 7.3 | 8 | Implemented and tested | Tidak |
| FR-037 | Publikasi hasil prediksi | Must | Inti | C-04, C-11 | 3.5, 7.3 | 8 | Implemented and tested | Tidak |
| FR-038 | Mode deteksi | Must | Inti | C-11 | 3.5 sampai 3.7 | 8 | Implemented and tested | Tidak |
| FR-039 | Default kompatibel | Must | Inti | C-11 | 3.5 sampai 3.7 | 8 | Implemented and tested | Tidak |
| FR-040 | Pemisahan aktivitas dan keputusan | Must | Inti | C-08, C-09 | 3.5 sampai 3.7 | 8 | Implemented and tested | Tidak |
| FR-041 | Probabilitas rendah | Must | Inti | C-09 | 3.5 sampai 3.7 | 8 | Implemented and tested | Tidak |
| FR-042 | Smoothing prediksi | Must | Inti | C-09 | 3.5 sampai 3.7 | 8 | Implemented and tested | Tidak |
| FR-043 | Toleransi offset | Must | Inti | C-09, C-24 | 3.5 sampai 3.7 | 6 | Implemented but not tested | Ya |
| FR-044 | State siklus | Must | Inti | C-08 | 6.1 | 8 | Existing and verified | Tidak |
| FR-045 | Senggolan singkat | Must | Inti | C-08 | 6.1 | 8 | Existing and verified | Tidak |
| FR-046 | Independen dari periode telemetri | Must | Inti | C-08 | 6.1 | 8 | Implemented and tested | Tidak |
| FR-047 | Jeda singkat | Must | Inti | C-08 | 6.1 | 8 | Existing and verified | Tidak |
| FR-048 | Syarat durasi minimum | Must | Inti | C-08 | 6.1 | 8 | Implemented and tested | Ya |
| FR-049 | Batas diam berbasis data | Must | Inti | C-08, C-24 | 6.1 | 6 | Implemented but not tested | Ya |
| FR-050 | Alasan selesai | Should | Tambahan | C-08 | 6.1 | 8 | Implemented and tested | Tidak |
| FR-051 | Koreksi saat mesin aktif lagi | Must | Inti | C-08 | 6.1 | 8 | Implemented and tested | Tidak |
| FR-052 | Alert sekali per penyelesaian | Must | Inti | C-08 | 6.1 | 8 | Existing and verified | Tidak |
| FR-053 | Stabilitas SPIN | Should | Tambahan | C-08 | 6.1 | 8 | Implemented and tested | Tidak |
| FR-054 | Watchdog HP A | Must | Inti | C-08, C-11 | 6.1 | 8 | Implemented and tested | Tidak |
| FR-055 | Pemulihan state | Should | Tambahan | C-08, C-12 | 6.1 | 8 | Implemented and tested | Tidak |
| FR-056 | Publikasi alert | Must | Inti | C-11 | 6.2, 7.2 | 8 | Existing and verified | Tidak |
| FR-057 | Pengingat | Must | Inti | C-08 | 6.2, 7.2 | 8 | Existing and verified | Tidak |
| FR-058 | Alarm HP B | Must | Inti | C-07 | 6.2, 7.2 | 8 | Existing but not verified | Tidak |
| FR-059 | Validasi alert | Must | Inti | C-04, C-06 | 6.2, 7.2 | 6 | Implemented and tested | Tidak |
| FR-060 | Alert ID dan dedupe | Should | Tambahan | C-04, C-06 | 6.2, 7.2 | 6 | Implemented and tested | Tidak |
| FR-061 | Alert setelah HP B offline | Should | Tambahan | C-06, C-11 | 6.2, 7.2 | 8 | Implemented and tested | Tidak |
| FR-062 | Alarm tidak menahan MQTT | Should | Tambahan | C-06, C-07 | 6.2, 7.2 | 8 | Implemented and tested | Tidak |
| FR-063 | Konfirmasi goyang | Must | Inti | C-08 | 6.2 | 8 | Existing and verified | Tidak |
| FR-064 | Goyangan di luar DONE diabaikan | Must | Inti | C-08 | 6.2 | 8 | Existing and verified | Tidak |
| FR-065 | Konfirmasi tahan guncangan | Must | Inti | C-08 | 6.2 | 8 | Implemented and tested | Tidak |
| FR-066 | Umpan balik konfirmasi | Should | Tambahan | C-07, C-11 | 6.2 | 8 | Implemented and tested | Tidak |
| FR-067 | Perintah ARM dan DISARM | Must | Inti | C-08, C-11 | 6.1, 7.2 | 8 | Existing and verified | Tidak |
| FR-068 | Kontrol dari CLI dan penolakan perintah | Should | Tambahan | C-11, C-15 | 6.1, 7.2 | 8 | Existing but not verified | Tidak |
| FR-069 | Status ARM akurat | Should | Tambahan | C-11 | 6.1, 7.2 | 6 | Implemented and tested | Tidak |
| FR-070 | Status utama | Must | Inti | C-13 | 7.4 | 8 | Existing and verified | Tidak |
| FR-071 | Grafik getaran | Must | Inti | C-13 | 7.4 | 8 | Existing and verified | Tidak |
| FR-072 | Koneksi dan kontrol | Must | Inti | C-13 | 7.4 | 8 | Existing and verified | Tidak |
| FR-073 | Konfigurasi tanpa kredensial | Must | Inti | C-14 | 7.4 | 8 | Existing and verified | Tidak |
| FR-074 | Panel model | Must | Inti | C-13 | 7.4 | 8 | Implemented and tested | Tidak |
| FR-075 | Istilah probabilitas | Must | Inti | C-13 | 7.4 | 8 | Implemented and tested | Tidak |
| FR-076 | Kualitas sensor | Should | Tambahan | C-13 | 7.4 | 8 | Implemented and tested | Tidak |
| FR-077 | Penjelasan dan riwayat | Should | Tambahan | C-13 | 7.4 | 8 | Implemented and tested | Tidak |
| FR-078 | Tanpa metrik rekaan | Must | Inti | C-13 | 7.4 | 8 | Implemented and tested | Tidak |
| FR-079 | Simulator sensor | Must | Inti | C-01 | 4.6, 7.1 | 8 | Existing and verified | Tidak |
| FR-080 | Demo offline | Should | Tambahan | C-16 | 4.6, 7.1 | 8 | Existing and verified | Tidak |
| FR-081 | Pemutaran ulang rekaman | Must | Inti | C-25 | 4.6, 7.1 | 4 | Implemented and tested | Tidak |
| FR-082 | Skenario regresi | Must | Inti | C-27 | 4.6, 7.1 | 8 | Implemented but not tested | Tidak |
| FR-083 | Fallback model | Must | Inti | C-10, C-11 | 7.5 | 8 | Implemented and tested | Tidak |
| FR-084 | Fitur tidak valid saat inference | Must | Inti | C-09, C-10 | 7.5 | 8 | Implemented and tested | Tidak |
| FR-085 | Kegagalan callback | Should | Tambahan | C-11 | 7.5 | 8 | Implemented and tested | Tidak |
| FR-086 | Detector tersambung kembali | Must | Inti | C-11 | 7.5 | 8 | Existing and verified | Tidak |
| FR-087 | Status offline | Should | Tambahan | C-05, C-11 | 7.5 | 8 | Existing but not verified | Tidak |
| NFR-001 | Latensi inference | Should | Tambahan | C-10 | 3.3, 9.2 | 5 | Implemented and tested | Tidak |
| NFR-002 | Latensi status | Should | Tambahan | C-11 | 3.3, 9.2 | 8 | Implemented and tested | Tidak |
| NFR-003 | Latensi notifikasi | Should | Tambahan | C-28 | 3.3, 9.2 | 8 | Planned | Ya |
| NFR-004 | Keterlambatan deteksi selesai | Must | Inti | C-24 | 3.3, 9.2 | 4 | Planned | Ya |
| NFR-005 | Pemulihan koneksi | Must | Inti | C-06 | 4.6, 7.5 | 1 | Implemented and tested | Tidak |
| NFR-006 | Uji ketahanan | Should | Tambahan | C-28 | 4.6, 7.5 | 8 | Implemented and tested | Tidak |
| NFR-007 | Alert palsu | Must | Inti | C-24 | 4.6, 7.5 | 4 | Planned | Ya |
| NFR-008 | Alert terlewat | Must | Inti | C-24 | 4.6, 7.5 | 4 | Planned | Ya |
| NFR-009 | Kerahasiaan kredensial | Must | Inti | C-14, C-28 | 7.2, 7.4, 7.5 | 8 | Existing and verified | Tidak |
| NFR-010 | TLS default | Must | Inti | C-05 | 7.2, 7.4, 7.5 | 8 | Existing but not verified | Tidak |
| NFR-011 | Broker berautentikasi | Should | Tambahan | C-05, C-13 | 7.2, 7.4, 7.5 | 8 | Implemented but not tested | Tidak |
| NFR-012 | Data minimal | Must | Inti | C-04 | 7.2, 7.4, 7.5 | 8 | Implemented and tested | Tidak |
| NFR-013 | Pemuatan model aman | Must | Inti | C-10 | 7.2, 7.4, 7.5 | 5 | Implemented and tested | Tidak |
| NFR-014 | Fungsi inti tanpa ML | Must | Inti | C-28 | 7.5 | 5 | Implemented and tested | Tidak |
| NFR-015 | State saat broker putus | Must | Inti | C-11 | 7.5 | 8 | Implemented and tested | Tidak |
| NFR-016 | Inti tanpa MQTT | Must | Inti | C-08, C-09 | 1, 7.6 | 6 | Existing but not verified | Tidak |
| NFR-017 | Regresi test lama | Must | Inti | C-27 | 1, 7.6 | 8 | Existing and verified | Tidak |
| NFR-018 | Definisi fitur tunggal | Must | Inti | C-03 | 1, 7.6 | 2 | Implemented and tested | Tidak |
| NFR-019 | Keterlacakan test | Should | Tambahan | C-27 | 1, 7.6 | 8 | Planned | Tidak |
| NFR-020 | Pemahaman dashboard | Could | Opsional | C-13 | 7.4 | 7 | Planned | Tidak |
| NFR-021 | Lebar layar | Should | Tambahan | C-13 | 7.4 | 7 | Implemented and tested | Tidak |
| NFR-022 | Panduan penyiapan | Should | Tambahan | C-28 | 7.4 | 8 | Implemented but not tested | Tidak |
| NFR-023 | Kebutuhan edge ringan | Must | Inti | C-28 | 1, 2.3 | 8 | Existing but not verified | Ya |
| NFR-024 | Sistem operasi laptop | Should | Tambahan | C-28 | 1, 2.3 | 8 | Existing but not verified | Tidak |
| NFR-025 | Lingkup kapasitas | Must | Inti | C-28 | 1, 2.3 | 8 | Existing but not verified | Tidak |
| NFR-026 | Memori terbatas | Could | Opsional | C-08 | 1, 2.3 | 8 | Planned | Tidak |
| NFR-027 | Training berulang | Must | Inti | C-23 | 3.4, 5.1 | 8 | Implemented and tested | Tidak |
| NFR-028 | Dependensi tercatat | Must | Inti | C-28 | 3.4, 5.1 | 3 | Implemented and tested | Tidak |
| NFR-029 | Label bukti pada hasil | Must | Inti | C-28 | 3.4, 5.1 | 8 | Implemented and tested | Tidak |
| DML-001 | Skema data mentah | Must | Inti | C-20 | 4.1 sampai 4.3 | 8 | Implemented and tested | Tidak |
| DML-002 | Skema sesi dan label | Must | Inti | C-20 | 4.1 sampai 4.3 | 8 | Implemented and tested | Tidak |
| DML-003 | Definisi kelas | Must | Inti | C-19 | 4.1 sampai 4.3 | 8 | Implemented and tested | Tidak |
| DML-004 | Zona transisi dan label ragu | Must | Inti | C-21 | 4.1 sampai 4.3 | 8 | Implemented and tested | Tidak |
| DML-005 | Kelas tambahan bersyarat | Could | Opsional | C-24 | 4.1 sampai 4.3 | 1 | Planned | Ya |
| DML-006 | Protokol pelabelan | Must | Inti | C-19 | 4.1 sampai 4.3 | 8 | Implemented but not tested | Ya |
| DML-007 | Validasi kualitas data | Must | Inti | C-21 | 4.1 sampai 4.3 | 8 | Implemented and tested | Tidak |
| DML-008 | Daftar fitur | Must | Inti | C-03 | 4.4 | 8 | Implemented and tested | Tidak |
| DML-009 | Jendela agregat | Must | Inti | C-03 | 4.4 | 8 | Implemented but not tested | Ya |
| DML-010 | Urutan fitur | Must | Inti | C-10 | 4.4 | 8 | Implemented and tested | Tidak |
| DML-011 | Split per siklus | Must | Inti | C-29 | 4.5 | 8 | Implemented and tested | Tidak |
| DML-012 | Kunci test set | Must | Inti | C-29 | 4.5 | 8 | Implemented and tested | Ya |
| DML-013 | Cross-validation kelompok | Should | Tambahan | C-29 | 4.5 | 8 | Implemented and tested | Tidak |
| DML-014 | Kecukupan data | Must | Inti | C-29 | 4.5 | 3 | Implemented and tested | Ya |
| DML-015 | Baseline | Must | Inti | C-23 | 3.3, 4.6 | 8 | Implemented and tested | Tidak |
| DML-016 | Kandidat dan seleksi | Must | Inti | C-23 | 3.3, 4.6 | 8 | Implemented and tested | Tidak |
| DML-017 | Metrik aktivitas | Must | Inti | C-24 | 3.3, 4.6 | 4 | Implemented and tested | Tidak |
| DML-018 | Metrik siklus | Must | Inti | C-24 | 3.3, 4.6 | 4 | Implemented but not tested | Tidak |
| DML-019 | Ketidakseimbangan kelas | Must | Inti | C-23 | 3.3, 4.6 | 3 | Implemented and tested | Tidak |
| DML-020 | Perbandingan empat kelompok | Must | Inti | C-08, C-24, C-25, C-26 | 3.3, 4.6 | 4 | Implemented but not tested | Ya |
| DML-021 | Generalisasi bersyarat | Should | Tambahan | C-24 | 3.3, 4.6 | 4 | Implemented but not tested | Ya |
| DML-022 | Metadata model | Must | Inti | C-23 | 3.4, 3.5 | 3 | Implemented and tested | Tidak |
| DML-023 | Versioning | Must | Inti | C-10 | 3.4, 3.5 | 3 | Implemented and tested | Tidak |
| DML-024 | Ambang probabilitas | Should | Tambahan | C-23 | 3.4, 3.5 | 4 | Implemented but not tested | Ya |
| DML-025 | Kalibrasi | Must | Inti | C-28 | 3.4, 3.5 | 4 | Implemented and tested | Tidak |
| DML-026 | Pernyataan batasan | Must | Inti | C-28 | 3.4, 3.5 | 4 | Implemented and tested | Tidak |
| DML-027 | Penyimpanan data pribadi | Should | Tambahan | C-28 | 3.4, 3.5 | 1 | Implemented and tested | Tidak |
