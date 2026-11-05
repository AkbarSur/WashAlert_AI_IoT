# Laporan Phase 4: Infrastruktur Dataset dan Fitur

Tanggal 4 November 2026. Kebutuhan mengacu pada SRS v0.3.

> **Phase 4 telah menyiapkan infrastruktur, tetapi pengumpulan data fisik belum dilakukan.** `data/real/` kosong. Tidak ada model yang dilatih, dan detector belum memakai ML.

## 1. Yang dibuat

| Komponen | File | Fungsi |
|---|---|---|
| Fitur | `shared/features.py` | Fitur jendela edge, agregat, urutan kolom. Dipakai edge dan dataset |
| Skema | `ml/dataset_io.py` | Kolom, label, satuan, baca-tulis file |
| Ukur | `ml/measure_sampling.py` | Laju nyata, gyro kosong, offset, cek satuan |
| Rekam | `ml/record_session.py` | Sampel mentah, metadata, tidak menimpa sesi |
| Label | `ml/label_session.py` | Interval observasi, video, sinkron waktu |
| Validasi | `ml/validate_dataset.py` | Aturan V01 sampai V20 |
| Dataset | `ml/build_dataset.py` | `windows.csv`, `raw_labeled.csv`, manifest, laporan kualitas |
| Split | `ml/split_dataset.py` | Train, validation, test per siklus, kunci, CV |
| Sintetis | `ml/generate_synthetic.py` | Data buatan bertanda jelas |

## 2. Perubahan modul lama

| File | Perubahan | Kebutuhan | Bukti regresi |
|---|---|---|---|
| `shared/processing.py` | `SensorSample` mendapat dua field opsional | FR-003 | `test_processing`, `test_sensor_sample_positional_form_unchanged` |
| `shared/sensors.py` | Menandai sampel basi dan `sensor_fault`. Nilai non-angka dianggap kosong | FR-003, FR-004 | `test_sensors` |
| `shared/messages.py` | Telemetri v2 opsional | FR-016 | `test_messages_v2`, `test_messages_alarm` |
| `shared/mqtt_connection.py` | `blocking=False`, reconnect. Bawaan tetap blocking | FR-023 | `test_mqtt_integration` |
| `shared/edge_runner.py` | Tidak crash saat koneksi putus, mengirim fitur v2 | FR-022, FR-016 | `test_mqtt_integration` |
| `nodes/detector_service/main.py` | Retry koneksi awal saja. **FSM dan alur alert tidak berubah** | FR-023 | `test_detector_starts_before_broker`, `test_full_cycle_alert_and_ack_unchanged` |
| `README.md`, `.gitignore` | Dokumentasi dan pengecualian data turunan | - | - |

Tidak diubah: `rules.py`, `alarm.py`, `dashboard/index.html`, `dashboard_server.py`, `hp_mesin.py`, `hp_pemilik.py`, `detector.py`, `send_control.py`, `offline_demo.py`, `requirements.txt`, dan empat file test lama.

## 3. Hasil pengujian yang benar-benar dijalankan

Perintah: `WASHALERT_SLOW=1 python -m unittest discover -s tests -t .` (Python 3.13, Linux, cloud).

| Run | Hasil |
|---|---|
| Semua, dengan broker lokal amqtt | **173 test, semua lulus** |
| Tanpa amqtt | 173 test: 168 lulus, 5 dilewati (test yang butuh broker) |
| 15 test lama | Lulus, keempat file identik dengan aslinya |

| Berkas | Jumlah | Cakupan |
|---|---:|---|
| `test_rules`, `test_processing`, `test_messages_alarm`, `test_dashboard_server` | 15 | Test lama |
| `test_sensors` | 9 | Mock `termux-sensor` |
| `test_features` | 21 | Fitur, batas jendela, data rusak |
| `test_messages_v2` | 9 | Kompatibilitas telemetri |
| `test_data_collection` | 26 | Perekam, label, alat ukur |
| `test_cli_fake_termux` | 3 | CLI sebagai proses dengan `termux-sensor` tiruan |
| `test_dataset_validation` | 31 | Aturan validasi |
| `test_build_dataset` | 22 | Dataset, zona transisi, kesamaan jalur fitur |
| `test_dataset_splitting` | 21 | Kebocoran, kunci, data kecil, hold-out mesin |
| `test_synthetic_policy` | 4 | Pemisahan sintetis |
| `test_backward_compat` | 5 | Alat lama, ketergantungan |
| `test_mqtt_integration` | 7 | Broker lokal: mati-hidup, siklus penuh |

Pemeriksaan tambahan:

- **Test baru peka terhadap bug lama:** test broker yang sama pada kode lama gagal dengan pesan "Edge mati saat broker putus" dan "Edge mati karena broker belum ada".
- **Pemulihan broker:** telemetri kembali 2,7–2,8 detik setelah broker hidup, pada 3 dari 3 restart. Ini broker lokal, jadi jangan diartikan sebagai waktu pada HiveMQ atau jaringan seluler.
- **Dashboard:** dijalankan dengan browser headless lewat kode baru. Status berubah sampai DONE, ARM dan DISARM bekerja, tanpa error JavaScript. Grafik belum diperiksa visual.
- **Kompatibilitas Python 3.10:** hanya pemeriksaan sintaks. Test dijalankan pada 3.13.

## 4. Yang belum terbukti

| Hal | Status |
|---|---|
| Perekam dan alat ukur di HP Android nyata | Belum. Hanya `termux-sensor` tiruan |
| Rekaman panjang saat layar mati | Belum |
| Termux pada Python yang terpasang di HP kalian | Belum |
| Koneksi TLS ke HiveMQ setelah perubahan | Belum. Uji memakai broker lokal tanpa TLS |
| Windows | Belum |
| Satuan rad/s dan m/s² dari `termux-sensor` | Belum, sampai alat ukur dijalankan |
| Ketukan sinkron pada sampling lambat | Mungkin tidak terdeteksi. Ada jalur alternatif |
| Daya pisah fitur pada mesin nyata | Belum diketahui |
| Nilai jendela 30 dtk, guard 10 dtk, ambang validasi | Diusulkan, belum divalidasi |

## 5. Keterbatasan implementasi

- Timestamp diambil setelah panggilan `termux-sensor` selesai, karena Termux tidak memberikan waktu per sampel pada jalur ini. Interval yang tercatat adalah interval baca, bukan waktu pengukuran sensor.
- `termux-sensor -n 3` masih membuang dua sampel (FR-007). Sengaja menunggu hasil ukur pada gerbang G1, agar pola akuisisi saat merekam dan saat runtime tetap sama.
- Perekam dan alat label berjalan pada jam perangkat masing-masing.
- Split pada data kecil hanya memberi gambaran. `evaluation_ready` bukan jaminan validitas statistik.
- Telemetri v2 sudah terkirim tetapi belum dipakai detector dan dashboard.
- CR-003 sampai CR-007 masih berstatus diusulkan, dan CR-006 menunggu keputusan.

## 6. Status kebutuhan

| Status | Jumlah |
|---|---:|
| Implemented and tested | 29 |
| Implemented but not tested | 4 |
| Existing and verified | 23 |
| Existing but not verified | 12 |
| Planned | 75 |

**Implemented and tested pada Phase 4 (perangkat lunak):** FR-002, FR-003, FR-004, FR-005, FR-010, FR-013, FR-016, FR-017, FR-022, FR-023, FR-024, FR-025, FR-026, FR-027, FR-028, FR-029, FR-030, NFR-005, NFR-018, DML-001, DML-002, DML-003, DML-004, DML-007, DML-008, DML-011, DML-012, DML-014, DML-027.

**Implemented but not tested (menunggu HP, gerbang G1, atau Phase 5):** FR-006, DML-006, DML-009, DML-013.

Rincian ada di `requirements_traceability_matrix.md`.

## 7. Kesiapan menuju Phase 5

| Syarat | Status |
|---|---|
| Pipeline rekam, label, validasi, dataset, split | Siap |
| Fitur sama antara dataset dan runtime | Siap |
| Data sintetis untuk menguji pipeline training | Siap |
| Laporan ukur HP A dan HP B | **Belum, kerja lapangan** |
| Sesi nyata pendek lolos validasi (gerbang G2) | **Belum, kerja lapangan** |
| Keputusan jendela dan akuisisi (gerbang G1) | **Menunggu hasil ukur** |
| Minimal 8 siklus nyata berlabel (diusulkan) | **Belum, kerja lapangan** |
| Split nyata terkunci | Menunggu data |
| Keputusan CR-006, deadline, jumlah mesin | **Menunggu kelompok** |

Kode training pada Phase 5 dapat dibuat dan diuji dengan data sintetis sekarang. Model final dan metrik yang dapat dilaporkan tetap membutuhkan data nyata.
