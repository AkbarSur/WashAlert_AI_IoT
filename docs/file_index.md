# Indeks File Akhir

| File | Tujuan | Lokasi | Status |
|---|---|---|---|
| README | Pengenalan dan cara pakai | `README.md` | Selesai. Isi nama tim dan tautan |
| Kode edge | HP A, HP B | `hp_mesin.py`, `hp_pemilik.py`, `shared/` | Teruji dengan simulator dan tiruan, belum di HP pada versi ini |
| Detector | MQTT, FSM, aktivitas, inference | `detector.py`, `nodes/detector_service/` | Teruji perangkat lunak |
| Dashboard | Pemantauan | `dashboard/`, `shared/dashboard_server.py` | Teruji di Chromium |
| Kontrol | ARM/DISARM CLI | `send_control.py` | Terbukti lewat test lama |
| Pipeline ML | Rekam sampai evaluasi | `ml/` | Teruji pada data sintetis dan tiruan |
| Model | Artefak | `models/development/SYNTHETIC_*` | Sintetis, hanya demo |
| Data sintetis | Uji pipeline | `data/synthetic/` (dibangun ulang, ada di zip) | Tersedia |
| Data nyata | Training final | `data/real/` | **Kosong** |
| Test | Otomatis | `tests/` | 386 lulus, tanpa HP |
| Hasil pengujian | Bukti | `reports/` | Tersedia |
| Konfigurasi | Contoh | `.env.example`, `demo/env.lokal.example`, `demo/broker_lokal.yaml` | Selesai |
| SRS, SDD, RTM, change log | Kebutuhan dan desain | `docs/` | Baseline usulan, belum disetujui kelompok |
| Laporan QA | Fase 8 | `docs/phase8_qa_report.md` | Selesai |
| Laporan teknis | Akademik | `docs/laporan_teknis_WashAlert_AI.md` | Selesai. Isi identitas |
| Dokumentasi ML | Akademik | `docs/ml_documentation.md` | Selesai |
| Presentasi | 25 slide dengan notes | `presentation/WashAlert_AI_presentasi.pptx` | Selesai. Isi nama dan tautan |
| Speaker notes | Latihan | `presentation/speaker_notes.md` | Selesai |
| Demo langsung | Panduan | `demo/panduan_live_demo.md` | Selesai. Jalur HP belum digladi |
| Rencana video | Storyboard | `demo/rencana_video.md` | Selesai. Video belum direkam |
| Tanya jawab | 28 pertanyaan | `demo/tanya_jawab_akademik.md` | Selesai |
| Panduan GitHub | Unggah | `docs/github_submission.md` | Selesai. Belum di-push |
