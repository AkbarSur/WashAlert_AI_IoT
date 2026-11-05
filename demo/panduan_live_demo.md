# Panduan Demonstrasi Langsung

Sebut sejak awal jenis demo yang dipakai. **Demo simulator dan rekaman sintetis membuktikan perangkat lunak berjalan, bukan akurasi pada mesin cuci.** Jalur HP nyata pada versi ini belum diuji oleh pembuat panduan, jadi latih dulu sebelum hari presentasi.

## Pilih jalur

| Jalur | Butuh | Risiko | Kapan dipakai |
|---|---|---|---|
| A. HP nyata + HiveMQ | 2 HP, internet | Belum pernah dijalankan pada versi ini | Jika lulus gladi |
| B. HP nyata + broker lokal | 2 HP, satu hotspot | Belum pernah dijalankan pada versi ini | Internet tidak stabil |
| C. Simulator + broker lokal | Laptop | Rendah | Cadangan |
| D. `scripts.e2e_demo` otomatis | Laptop, sekitar 8 menit | Rendah | Cadangan terakhir, atau rekaman |

## Daftar periksa sebelum demo

- [ ] HP A: Termux dan Termux:API terpasang, baterai penuh, layar tidak mati sendiri
- [ ] HP A dan HP B: `termux-sensor -l` menampilkan accelerometer dan gyroscope
- [ ] HP B: izin notifikasi aktif, `termux-vibrate -d 500` bergetar
- [ ] Jam HP dan laptop selisih kurang dari 30 detik
- [ ] `PROJECT_ID` sama di ketiga perangkat
- [ ] WiFi atau hotspot tersambung. Untuk jalur A, internet aktif
- [ ] `python -m scripts.offline_demo` berjalan di laptop
- [ ] Detector berjalan, dashboard di `http://localhost:8000` menunjukkan "Tersambung"
- [ ] Mode di dashboard sesuai rencana, dan banner model terbaca
- [ ] Uji alert dan goyangan sekali sebelum presentasi
- [ ] Rekaman cadangan jalur D sudah disiapkan

## Persiapan laptop

Jalur A:

```bash
cp .env.example .env     # samakan PROJECT_ID
python detector.py
```

Jalur B dan C, tiap perintah di terminal sendiri:

```bash
cp demo/env.lokal.example .env
amqtt -c demo/broker_lokal.yaml
python detector.py
```

Mode HYBRID dengan model sintetis:

```bash
DETECTION_MODE=HYBRID ALLOW_SYNTHETIC_MODEL=true \
MODEL_PATH=models/development/SYNTHETIC_syn_hard_v1-v1-decision_tree-F2-624d6645 python detector.py
```

HYBRID baru memakai model setelah sekitar 20 detik data, karena jendela agregat harus terisi. Sampai saat itu panel AI menampilkan fallback, dan itu normal.

## HP (jalur A dan B)

Untuk jalur B, di `.env` HP isi `MQTT_HOST` dengan IP laptop, `MQTT_PORT=1883`, `MQTT_TLS=false`, `ALLOW_INSECURE_LOCAL=true`. Firewall laptop harus mengizinkan port 1883.

```bash
python hp_mesin.py       # HP A
python hp_pemilik.py     # HP B
```

## Simulator (jalur C)

```bash
python hp_mesin.py --source simulator --scenario washer
python hp_pemilik.py --source simulator --scenario ack
```

Skenario `washer` menjalankan satu siklus sejak proses mulai: diam, cuci mulai detik ke-4, spin detik ke-16, berhenti detik ke-24. Skenario `ack` menggoyang HP B pada detik ke-40 sampai 44.

Dashboard menampilkan **MODE SIMULASI**. Jangan menutupinya.

## Urutan demo

| Langkah | Lakukan | Yang terlihat |
|---|---|---|
| 1 | Biarkan HP A diam | Status `IDLE` |
| 2 | Geser HP A pelan selama sekitar 10 detik | `WASHING`, grafik naik |
| 3 | Goyang HP A keras | `SPIN` |
| 4 | Diamkan sekitar 3 detik, lalu gerakkan lagi | Belum `DONE`. Tunjukkan linimasa |
| 5 | Diamkan sekitar 10 detik | `DONE`, HP B bergetar, panel alert menunggu konfirmasi |
| 6 | Tunggu 20 detik pada mode demo | Pengingat |
| 7 | Goyang HP B kuat | `IDLE`, alert "Dikonfirmasi pemilik" |
| 8 | Klik DISARM, konfirmasi, lalu ARM | "Detector mengonfirmasi" |

Waktu mengikuti `CUCI_MODE=demo`: mulai 6 detik, selesai 8 detik, pengingat 20 detik. Pada jalur HP, hasil gerakan tangan bisa berbeda, jadi coba dulu saat gladi.

## Pemulihan

| Masalah | Tindakan |
|---|---|
| Dashboard "Terputus" | Periksa jaringan. Dashboard menyambung ulang sendiri. Jika tetap gagal, pindah ke jalur C |
| Dashboard "Belum ada" | Detector tidak berjalan, atau `PROJECT_ID` berbeda |
| HP A "data usang" | Termux mungkin tertidur. Buka lagi, atau naikkan `DASHBOARD_STALE_S` |
| Sensor tidak terbaca | `termux-sensor -c`, jalankan ulang program |
| Telemetri ditolak basi | Samakan jam |
| Tidak mencapai `DONE` | Panel kualitas dan grafik: RMS diam mungkin di atas ambang. Sesuaikan `CUCI_STILL_TH` setelah melihat nilainya |
| HP B tidak bergetar | Coba `termux-vibrate`. Dashboard tetap menunjukkan alert |
| Port 8000 terpakai | Ubah `DASHBOARD_PORT` |
| Semua gagal | Jalur D, atau putar rekaman |

## Cadangan otomatis

```bash
python -m ml.generate_synthetic --difficulty hard   # sekali saja, jika data/synthetic belum ada
python -m scripts.e2e_demo --model models/development/SYNTHETIC_syn_hard_v1-v1-decision_tree-F2-624d6645 --browser --out reports/e2e/gladi
```

Hasilnya `e2e_report.json` dan screenshot. Pada hasil terakhir, ada data WASHING yang terbaca SPIN oleh model sintetis. Jika ditanya, jelaskan apa adanya.
