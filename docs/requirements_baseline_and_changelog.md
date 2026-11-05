# Baseline dan Change Log Kebutuhan: WashAlert AI

## Baseline

| Baseline | Status | Isi | Disetujui oleh |
|---|---|---|---|
| BL-0.1 | Digantikan BL-0.2 | 143 kebutuhan, SRS v0.1, RTM v0.1 | Belum ada |
| BL-0.2 | Digantikan BL-0.3 | SRS v0.2, RTM v0.2, SDD v0.1 | Belum ada |
| BL-0.3 | Digantikan BL-0.4 | SRS v0.3, RTM v0.3, SDD v0.2 | Belum ada |
| BL-0.4 | Digantikan BL-0.5 | SRS v0.4, RTM v0.4, SDD v0.3 | Belum ada |
| BL-0.5 | Digantikan BL-0.6 | SRS v0.5, RTM v0.5, SDD v0.4 | Belum ada |
| BL-0.6 | Digantikan BL-0.7 | SRS v0.6, RTM v0.6, SDD v0.5 | Belum ada |
| BL-0.7 | Diusulkan; baseline kerja, belum disetujui formal | 143 kebutuhan, SRS v0.7, RTM v0.7, SDD v0.6 | Belum ada |

## Daftar periksa persetujuan

- [ ] Sumber Q-1 sudah dijawab: ketentuan dosen untuk upgrade AI.
- [ ] Lingkup dan daftar "tidak termasuk" disetujui.
- [ ] Kelas IDLE, WASHING, SPIN dan definisinya disetujui.
- [ ] Mode `RULE_ONLY`, `HYBRID`, dan `ML_ONLY` eksperimen disetujui (CR-009).
- [ ] Prioritas Must, terutama saat waktu terbatas, disetujui.
- [ ] Target numerik "diusulkan" diterima sebagai target awal.
- [ ] Rencana perbandingan empat kelompok disetujui.

## Prosedur perubahan

1. Tulis CR berisi ID, alasan, kebutuhan terdampak, dampak pada desain dan test.
2. Setujui oleh kelompok.
3. Perbarui SRS dan RTM dalam perubahan yang sama, lalu naikkan versi.

Kebutuhan tidak boleh diubah diam-diam saat implementasi.

## Change log

| ID | Tanggal | Perubahan | Alasan | Terdampak | Status |
|---|---|---|---|---|---|
| CR-000 | 2026-11-04 | Draf awal SRS, RTM, diagram | Permintaan kelompok, Project Instructions §22 | Semua | Diusulkan |
| CR-001 | 2026-11-04 | Alur kerja menjadi 9 fase dengan SRS sebagai fase 2 | Permintaan kelompok | Roadmap audit | Diusulkan |
| CR-002 | 2026-11-04 | Koreksi audit: pembacaan sensor pernah berjalan pada satu HP, menurut screenshot; yang belum ada adalah dataset nyata | Screenshot Termux pada arsip | SRS 2.2, FR-001 | Diusulkan |
| CR-003 | 2026-11-04 | Topik `events` diganti `alert_state` retained | Satu mekanisme menyelesaikan konfirmasi dan HP B yang baru tersambung | SRS 5.2, 5.5, 5.7, diagram 02 dan 06, FR-066, FR-061 | Diusulkan |
| CR-004 | 2026-11-04 | `SENSOR_LOST` tidak berlaku dari DONE, dan `spin_seen` menjadi flag | Prototipe: HP A mati saat DONE tidak boleh menghentikan pengingat; setelah spin, aktivitas dapat melewati WASHING | SRS 7.6, diagram 08, FR-054 | Diusulkan |
| CR-005 | 2026-11-04 | `done_hold_s` adalah nama konsep untuk `Config.done_s` dan `CUCI_DONE_S`; arm pembanding memakai salinan beku `legacy_rules.py` | Tidak menambah parameter ganda, pembanding lama tidak berubah | SDD, DML-020 | Diusulkan |
| CR-006 | 2026-11-04 | Tambah `abandon_s`: siklus di bawah `min_run_s` yang diam lama kembali ke IDLE tanpa alert | Prototipe: getaran singkat membuat state WASHING menggantung | FR-048, SDD 9.5 | Menunggu keputusan kelompok; belum masuk kebutuhan SRS |
| CR-007 | 2026-11-04 | Skema raw v2 (`dt_s`, `valid`), karantina baris rusak menggantikan penolakan file, modul baru `ml/split_dataset.py` dan `ml/dataset_io.py`, `raw_labeled.csv`, `--label` untuk sesi satu kondisi | Temuan implementasi Phase 4: baris terakhir dapat terpotong saat listrik mati; split perlu ada sebelum training; pengguna meminta train, validation, test | SDD 5, `dataset_schema.md`, DML-011 | Diusulkan |
| CR-008 | 2026-11-04 | `models/development` dan `models/production`, `reports/experiments`, modul `ml/metrics.py`, `ml/figures.py`, `ml/predict.py`, `ml/baselines/rule_activity.py`; validasi CV pada siklus, sesi non-siklus selalu training; flag `out_of_training_range`; laptop ML butuh Python ≥ 3.12 untuk versi tersemat | Temuan implementasi Phase 5 | SDD 5, SRS 2.6, DML-016 | Diusulkan |
| CR-009 | 2026-11-04 | `ML_ONLY` menjadi mode runtime eksperimen. Prediksi tak tersedia menghasilkan `UNKNOWN` yang menahan timer, menggantikan "aktivitas terakhir dipertahankan" | Prompt Phase 6 §6 meminta tiga mode. Mempertahankan aktivitas IDLE terakhir dapat memicu DONE palsu saat model gagal | FR-038, SDD mode deteksi | Diusulkan |
| CR-010 | 2026-11-04 | Field status tambahan `model_status`, `inference_latency_ms`, `spin_seen`, `alert_kind`, `activity_reason`; data sensor rusak pada semua mode menahan timer FSM; `state_store` aktif hanya jika `DETECTOR_STATE_PATH` diisi; `ALLOW_SYNTHETIC_MODEL`; log `[EVENT]` JSON; `ml/compare_arms.py`, `scripts/e2e_demo.py` | Prompt Phase 6 §7, §9, STEP 10, §14; temuan saat implementasi | FR-037, FR-055 | Diusulkan |
| CR-011 | 2026-11-05 | Dashboard memakai aset lokal (`dashboard/assets`, MQTT.js dan font tersimpan) menggantikan CDN. Field baru: status `last_command`, `alert_state.ended_by`, telemetri `data_source`, `/config.json` `stale_after_s` dan `offline_after_s`. `DASHBOARD_HOST` opsional. Pemilihan mode, konfirmasi dari dashboard, dan uji notifikasi tidak diimplementasikan | Prompt Phase 7 §5, §9, §H. Konfirmasi harus lewat HP B dan mode hanya berubah lewat restart menurut SRS | FR-072, FR-074, SDD dashboard | Diusulkan |
| CR-012 | 2026-11-05 | Model sintetis ikut dilacak Git, `scripts/soak_test.py`, `tests/test_release_consistency.py`, `demo/` dan `presentation/` | Phase 8 dan 9: demo dari clone baru, uji ketahanan, pemeriksaan paket. Tidak mengubah perilaku sistem | NFR-006 | Diusulkan |
