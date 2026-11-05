# Mengunggah ke GitHub

Repository belum saya push. Sesi pengerjaan tidak tersambung ke akun GitHub, dan keputusan publik atau privat ada pada kelompok. File ini belum berupa repository Git. Daftar file yang akan dilacak sudah diperiksa dengan `git init` pada salinan sementara: sekitar 180 file dan kurang dari 15 MB, tanpa `.env` dan data sintetis.

## Sebelum push

1. Isi nama dan NIM pada README, laporan teknis, dan slide 1.
2. Periksa `LICENSE`. Pemegang hak tertulis "PocketGuard IoT contributors", terbawa dari proyek asal.
3. Putuskan CR yang masih diusulkan, lihat `requirements_baseline_and_changelog.md`.

## Perintah

Buat repository kosong di GitHub dulu, sebaiknya **privat** sampai kelompok setuju.

```bash
cd WashAlert-AI
git init -b main
git add -A
git status                     # pastikan .env dan data/synthetic tidak muncul
git commit -m "WashAlert AI: rilis akademik"
git remote add origin https://github.com/<akun>/<repo>.git
git push -u origin main
```

Setelah itu, cantumkan tautannya pada README dan slide 25.

## Cek setelah clone

```bash
git clone https://github.com/<akun>/<repo>.git uji && cd uji
python -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-ml.txt -r requirements-dev.txt
python -m scripts.offline_demo
python -m ml.generate_synthetic --difficulty hard
python -m unittest discover -s tests -t .
```

Data sintetis tidak dilacak karena dapat dibuat ulang dengan seed tetap. Model sintetis dilacak agar demo dapat berjalan.
