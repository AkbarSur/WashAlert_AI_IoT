# Rencana Video Demonstrasi

Durasi sasaran sekitar 6 menit. Tampilkan teks "SIMULASI" di layar pada setiap adegan yang memakai simulator atau rekaman sintetis. **Video tidak boleh menyatakan bahwa sistem terbukti akurat pada mesin cuci.**

Pilih satu versi sebelum merekam:

- **Versi nyata:** HP A di atas mesin cuci sungguhan. Lengkapi hasilnya hanya jika benar terjadi.
- **Versi simulasi:** tangan menggerakkan HP, atau simulator. Sebutkan itu dalam narasi.

## Storyboard

| No | Durasi | Gambar | Narasi |
|---|---:|---|---|
| 1 | 15 dtk | Judul dan nama kelompok | "Kami Kelompok 12, memperkenalkan WashAlert AI." |
| 2 | 25 dtk | Mesin cuci di kos | "Mesin selesai, tetapi tidak ada yang tahu. Cucian tertinggal dan antrean tertahan." |
| 3 | 25 dtk | HP A di atas mesin, HP B di tangan | "HP A membaca getaran. HP B memberi alarm dan menerima konfirmasi." |
| 4 | 25 dtk | Terminal `hp_mesin.py` | "Accelerometer dan gyroscope dibaca lewat Termux, dan HP menghitung fitur sendiri." |
| 5 | 25 dtk | Log detector dan telemetri | "Fitur dikirim lewat MQTT ke laptop. Status dan alert kembali lewat broker yang sama." |
| 6 | 25 dtk | Terminal detector, baris mode | "Detector berjalan dalam mode HYBRID. Model kami masih dilatih dari data sintetis, dan dashboard menandainya." |
| 7 | 30 dtk | Dashboard, panel AI | "Model hanya menebak aktivitas. Keputusan selesai dibuat finite state machine." |
| 8 | 25 dtk | `WASHING` dan grafik naik | "Mesin mencuci, grafik getaran naik." |
| 9 | 20 dtk | `SPIN` | "Getaran keras terbaca sebagai fase peras." |
| 10 | 25 dtk | Jeda, linimasa, belum `DONE` | "Mesin berhenti sebentar. Aktivitas IDLE, tetapi status belum DONE, karena mesin yang diam belum tentu selesai." |
| 11 | 25 dtk | `DONE` | "Setelah diam cukup lama, FSM menyatakan selesai." |
| 12 | 20 dtk | HP B bergetar, notifikasi | "HP B bergetar dan menampilkan notifikasi." |
| 13 | 20 dtk | Goyang HP B, status `IDLE` | "Pemilik menggoyang HP, dan siklus berakhir." |
| 14 | 30 dtk | Model dirusak, banner fallback | "Jika model gagal, sistem memakai aturan, dan dashboard menyebut alasannya." |
| 15 | 35 dtk | Slide keterbatasan | "Kelebihan: perilaku lebih andal dan semua kegagalan terlihat. Keterbatasan: model belum divalidasi pada mesin cuci nyata." |

## Rekaman layar

- [ ] Dashboard satu layar penuh, zoom cukup besar
- [ ] Banner model dan simulasi terlihat
- [ ] Terminal detector dengan baris mode
- [ ] Linimasa saat jeda
- [ ] Panel alert sebelum dan sesudah konfirmasi
- [ ] Banner fallback
- [ ] Tidak ada `.env`, kata sandi, atau data pribadi di layar

## Rekaman kamera

- [ ] HP A di atas mesin, terpasang aman
- [ ] Mesin cuci beroperasi, jika memakai versi nyata
- [ ] HP B bergetar, terdengar atau terlihat jelas
- [ ] Tangan menggoyang HP B
- [ ] Layar HP terbaca
- [ ] Wajah penghuni dan kamar tidak terekam tanpa izin

## Perintah

Lihat [panduan_live_demo.md](panduan_live_demo.md). Untuk adegan 14, salin folder model, tambahkan satu baris ke `model.joblib` salinan itu, lalu jalankan detector dengan `MODEL_PATH` mengarah ke salinan. Jangan merusak artefak asli.

## Perilaku yang diharapkan

| Adegan | Harus terlihat |
|---|---|
| 6 | `Mode diminta HYBRID, mode efektif HYBRID` dan peringatan model sintetis |
| 7 | Sumber aktivitas "Model" setelah sekitar 20 detik data |
| 10 | Status tidak berubah menjadi `DONE` |
| 13 | Riwayat "Dikonfirmasi pemilik" |
| 14 | `fallback: model_hash_mismatch` tampil sebagai "file model berubah atau rusak" |

## Jika gagal saat merekam

| Masalah | Tindakan |
|---|---|
| HP putus | Rekam ulang adegan, jangan disunting seolah berhasil |
| Internet buruk | Pindah ke broker lokal, sebutkan dalam narasi |
| Model salah kelas | Biarkan, atau jelaskan. Jangan memotong untuk menyembunyikan hasil lalu mengklaim akurat |
| Mesin cuci tidak tersedia | Pakai versi simulasi |
