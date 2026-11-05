# Panduan Pengguna Dashboard WashAlert AI

## Membuka dashboard

1. Jalankan `python detector.py` di laptop. Dashboard ikut berjalan.
2. Buka alamat yang tercetak, biasanya `http://localhost:8000`.
3. Untuk melihat dari HP di jaringan yang sama, isi `DASHBOARD_HOST=0.0.0.0` di `.env`, lalu buka `http://<alamat-laptop>:8000`. Halaman ini tidak punya login, jadi pakai hanya di jaringan tepercaya.

Dashboard terhubung ke broker lewat `MQTT_WS_URL`. Jika broker memakai akun, form login muncul. Isiannya hanya disimpan di memori tab.

## Membaca layar

| Bagian | Artinya |
|---|---|
| Lingkaran pintu mesin | Status siklus, keputusan FSM di detector |
| Aktivitas mesin | Yang terbaca dari sensor saat ini: IDLE, WASHING, SPIN, atau UNKNOWN |
| Prediksi AI | Hasil model jika model benar-benar dipakai pada jendela itu |
| Linimasa siklus | Tiga jalur sejajar: status siklus, aktivitas, dan sumber aktivitas |
| Perangkat | Keadaan HP A, HP B, dan detector |
| Notifikasi | Alert aktif dan riwayat sejak halaman dibuka |
| Kualitas data HP A | Laju sampling nyata, sampel basi, keadaan sensor, sumber data |

**IDLE bukan DONE.** Mesin dapat IDLE saat jeda di tengah siklus. DONE hanya muncul setelah FSM menyatakan siklus selesai.

**Warna selalu disertai teks.** Hijau berarti normal, biru informasi, kuning peringatan, merah galat.

## Keadaan data

| Tampilan | Artinya | Yang dilakukan |
|---|---|---|
| Memuat | Menunggu koneksi dan laporan pertama | Tunggu |
| Belum ada | Tersambung, tetapi detector belum pernah melapor | Jalankan detector, periksa `PROJECT_ID` |
| Live | Data baru masuk dalam 20 detik terakhir | Tidak ada |
| Data usang | Tidak ada data baru selama 20 sampai 60 detik | Periksa Termux di HP |
| Offline | Tidak ada data lebih dari 60 detik, atau detector mengirim status OFFLINE | Jalankan ulang perangkat |
| Tidak diketahui, broker putus | Browser kehilangan broker, sehingga keadaan perangkat tidak terlihat | Periksa internet. Dashboard menyambung ulang otomatis |

Batas 20 dan 60 detik adalah usulan. Sesuaikan dengan `DASHBOARD_STALE_S` dan `DASHBOARD_OFFLINE_S` setelah periode telemetri HP terukur.

## Kontrol

- **ARM** memulai pemantauan.
- **DISARM** menjeda pemantauan dan mereset siklus, jadi dashboard meminta konfirmasi dulu.

Pesan "Detector mengonfirmasi" hanya muncul setelah detector menerbitkan balasan. Jika tidak ada balasan dalam 8 detik, dashboard melaporkan batas waktu dan status tidak diubah.

**Konfirmasi cucian dilakukan dengan menggoyang HP B.** Dashboard hanya menampilkan hasilnya.

## Label yang perlu dibaca

- **MODEL PENGEMBANGAN (SINTETIS):** model dilatih dari data sintetis. Prediksinya bukan bukti performa.
- **MODE SIMULASI:** data sensor berasal dari simulator atau rekaman sintetis.
- **Probabilitas prediksi, belum terkalibrasi:** nilai keluaran model, bukan peluang benar yang terjamin.
- **Riwayat sejak halaman dibuka:** riwayat hilang saat halaman dimuat ulang, karena tidak disimpan di server.

## Masalah umum

| Gejala | Periksa |
|---|---|
| "Belum dikonfigurasi" | `MQTT_WS_URL` di `.env` |
| "Tidak diizinkan" | Akun broker |
| HP A selalu usang | Periode telemetri nyata. Naikkan `DASHBOARD_STALE_S` |
| "Selisih jam HP" besar | Jam HP. Selisih lebih dari 30 detik membuat detector menolak telemetri |
