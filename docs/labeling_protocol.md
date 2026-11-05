# Protokol Pelabelan Ground Truth: WashAlert AI

Label berasal dari **observasi manusia**. Label tidak boleh diambil dari status detector, keluaran FSM, atau prediksi model, karena model hanya akan meniru aturan lama.

## 1. Definisi label

### IDLE

| Aspek | Isi |
|---|---|
| Definisi operasional | Motor mati dan tabung tidak bergerak |
| Kondisi fisik | Hening dari motor. Air boleh mengalir |
| Mulai | Saat gerakan tabung berhenti |
| Akhir | Saat gerakan tabung dimulai |
| Contoh | Sebelum mulai, rendam, pengisian air, setelah selesai |
| Ambiguitas | Motor berhenti sesaat di antara ayunan pencucian |
| Cara menghindari salah | Jeda kurang dari sekitar 5 detik di dalam pencucian tetap WASHING. Jeda yang lebih lama menjadi IDLE |

### WASHING

| Aspek | Isi |
|---|---|
| Definisi operasional | Tabung atau pulsator bergerak untuk mencuci atau membilas, tanpa putaran peras cepat |
| Kondisi fisik | Gerakan berayun, suara air teraduk |
| Mulai | Ayunan pertama yang berlanjut |
| Akhir | Gerakan berhenti, atau mulai peras |
| Contoh | Cuci utama, bilas |
| Ambiguitas | Awal putaran peras yang masih pelan |
| Cara menghindari salah | Saat ragu apakah sudah peras, pakai UNCERTAIN |

### SPIN

| Aspek | Isi |
|---|---|
| Definisi operasional | Tabung berputar cepat satu arah untuk memeras |
| Kondisi fisik | Suara berdengung naik, air terbuang |
| Mulai | Saat putaran jelas cepat |
| Akhir | Saat putaran mulai melambat |
| Contoh | Peras antar bilasan, peras akhir |
| Ambiguitas | Masa percepatan dan perlambatan |
| Cara menghindari salah | Tandai UNCERTAIN selama masa itu jika tidak jelas. Zona transisi juga dibuang otomatis |

### UNCERTAIN

Pakai saat pengamat tidak melihat atau mendengar mesin, ragu, HP tersentuh, atau saat ketukan sinkron.

**UNCERTAIN tidak pernah masuk data training.** Memakai UNCERTAIN bukan kesalahan: label ragu yang dipaksakan justru merusak model.

## 2. Yang bukan label

| Hal | Perlakuan | Alasan |
|---|---|---|
| DONE | Ditolak alat | Diam setelah selesai tampak sama dengan jeda. DONE diputuskan FSM dari riwayat |
| PAUSE | Pakai IDLE, dengan `phase_note` jika perlu | Sinyalnya diam. Kelas baru hanya melalui Change Request (DML kelas tambahan) |
| TRANSITION | Dibuang otomatis, atau UNCERTAIN | Tidak ada definisi fisik yang konsisten |

Jeda terpanjang di dalam siklus dihitung dari interval IDLE, untuk menetapkan `CUCI_DONE_S` pada Phase 5.

## 3. Aturan saat mengamati

1. Satu pengamat utama per sesi. Ia hanya mengamati kondisi mesin, tidak melihat dashboard.
2. Tekan tombol saat perubahan **terjadi**, bukan setelah menebak fase berikutnya.
3. Jangan mengisi label dari timer panel mesin.
4. Jika meninggalkan mesin: tekan `u` sebelum pergi, dan tekan label sesuai kondisi saat kembali.
5. Jangan menyunting `labels.csv` diam-diam. Koreksi dicatat di `--notes`, dengan alasannya.
6. Jangan menyentuh HP A selama sesi. Jika tersentuh, tandai `u` selama momen itu.

## 4. Pemeriksaan ulang

Minimal satu siklus direkam video dan dilabeli ulang oleh anggota kedua secara terpisah (`--from-events`). Bandingkan kedua `labels.csv`, lalu catat selisih waktu dan perbedaan label. Jika banyak perbedaan, definisi perlu diperjelas sebelum merekam lagi.

## 5. Keterbatasan

Pengamat tidak dapat menandai perubahan tepat ke milidetik. Selisih jam antar perangkat juga mungkin ada. Zona ±10 detik (diusulkan) mengurangi dampaknya, tetapi jika selisih jam lebih besar, jendela dekat perubahan fase dapat tetap salah label.
