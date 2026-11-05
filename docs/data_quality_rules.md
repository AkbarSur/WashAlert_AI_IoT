# Aturan Kualitas Data dan Pembagian Dataset

Diimplementasikan di `ml/validate_dataset.py`, `ml/build_dataset.py`, dan `ml/split_dataset.py`. **Tidak ada imputasi:** nilai yang hilang tidak pernah diisi.

## 1. Aturan validasi

| Kode | Masalah | Tindakan | Alasan |
|---|---|---|---|
| V01 | `raw.csv` tidak ada, atau kolom salah | REJECT sesi | Skema tidak dapat dipercaya |
| V02 | Nilai hilang, bukan angka, NaN, Infinity, seq duplikat | QUARANTINE baris. REJECT jika lebih dari 1% | Baris terakhir dapat terpotong saat listrik mati; kerusakan besar menandakan file rusak |
| V03 | seq atau `t_mono_s` mundur, `t_epoch_ms` ≤ 0, semua timestamp sama | REJECT sesi | Perekam selalu berurutan. Tidak diurutkan otomatis |
| V04 | Metadata hilang, rusak, atau `operator` berisi spasi | REJECT sesi | Identitas wajib, nama lengkap ditolak |
| V05 | `session_id` tidak valid, tidak cocok, baris atau label milik sesi lain | REJECT sesi | Mencegah rekaman tercampur |
| V06 | `data_kind` tidak cocok dengan folder, atau real bukan dari android | REJECT sesi | Data sintetis tidak boleh tampak nyata |
| V07 | Label hilang, tidak dikenal, terbalik, tumpang tindih | REJECT sesi | Ground truth tidak jelas |
| V08 | Label di luar rentang rekaman | WARN | Bagian itu tidak terpakai |
| V09 | Gap lebih dari 5× median | WARN, jendela dibuang | Waktu sampel tidak dapat diandalkan |
| V10 | Sampel memakai nilai sensor lama | MARK_INVALID. Jendela dengan segar < 60% tidak dipakai | Nilai lama bukan pengukuran |
| V11 | Sumbu bernilai sama sepanjang sesi, atau sensor sempat gagal | WARN | Perlu diperiksa manusia |
| V12 | Magnitude saat IDLE di luar 8,5–11 m/s² | WARN | Offset, tetapi masih m/s² |
| V13 | Siklus tanpa SPIN | WARN | Mungkin program tanpa spin, atau label salah |
| V14 | Satuan tercatat salah, magnitude 0,5–1,5, atau tidak wajar | REJECT sesi | Tampak dalam g. Tidak dikonversi diam-diam |
| V15 | Gyro saat IDLE di atas 0,3 | WARN | Mungkin bukan rad/s, atau label salah |
| V16 | File kosong, atau kurang dari 10 baris | REJECT sesi | Tidak ada data |
| V18 | Status bukan `complete` | WARN | Rekaman putus tetap dapat dipakai |
| V19 | Jam epoch mundur | WARN | Jam HP dapat disesuaikan. `t_mono_s` menjadi acuan |
| V20 | Magnitude di atas 200 m/s² | MARK_INVALID, jendela dibuang | Di luar rentang wajar |

Satuan rad/s tidak dapat dibuktikan sepenuhnya dari data: V15 hanya petunjuk. Dokumentasi Android menyatakan rad/s, dan ini perlu diperiksa dengan `ml.measure_sampling` di HP kalian.

Ambang di atas adalah nilai awal yang diusulkan, dan perlu ditinjau setelah data nyata pertama.

## 2. Laporan kualitas

`ml.build_dataset` menulis `quality_report.md` dan `.json`: jumlah baris total, dapat dipakai, tidak valid, dikarantina, sesi ditolak, jendela per label, serta alasan pembuangan per sesi. Baris yang dikarantina disimpan di `quarantine.csv`.

| Alasan pembuangan | Arti |
|---|---|
| `edge_sampel_kurang` | Jendela kekurangan sampel, sering di akhir sesi, atau ada baris dikarantina |
| `edge_gap` | Ada gap di dalam jendela |
| `edge_sampel_tidak_valid` | Magnitude ekstrem |
| `edge_terlalu_banyak_stale` | Segar < 60% |
| `agregat_data_kurang` | Belum mencapai syarat jendela agregat |
| `agregat_label_campur_atau_transisi` | Mencakup lebih dari satu label, atau dekat perubahan fase |
| `agregat_uncertain_atau_tanpa_label` | Mencakup UNCERTAIN, atau tidak terlabel |

## 3. Pembagian dataset

Jendela berdekatan sangat mirip dan saling tumpang tindih. Split acak per baris akan menaruh potongan siklus yang sama di train dan test, dan membuat skor tampak bagus secara palsu.

| Aturan | Implementasi |
|---|---|
| Satuan pembagian | `cycle_id`, atau `session_id` untuk sesi non-siklus |
| Rasio | Sekitar 60/20/20 per jumlah **siklus**, bukan per baris |
| Test | Minimal 2 siklus jika tersedia |
| Pemilihan | Acak dengan seed. Diulang agar ketiga kelas ada di tiap bagian bila mungkin |
| Mesin | `--holdout-machine` menaruh seluruh mesin di test. Butuh minimal 2 mesin |
| Cross-validation | `cv_folds_leave_one_cycle_out` pada train + validation, tanpa test |
| Kunci | `split_*.json` tidak dapat ditimpa, dan menyimpan hash `windows.csv` |

Alasan rasio: dengan 8 siklus, hasilnya 4 train, 2 validation, 2 test. Test yang lebih kecil terlalu bergantung pada satu siklus, sedangkan train yang lebih kecil belum tentu mencakup variasi program.

`evaluation_ready` hanya benar jika data nyata, minimal 8 siklus (diusulkan), minimal 2 siklus test, dan semua kelas tercakup. Jika tidak, split tetap dapat dibuat untuk pengembangan, dengan peringatan. Satu siklus ditolak.

**Preprocessing:** pipeline Phase 4 tidak menghitung statistik lintas sesi. Scaler harus berada dalam `Pipeline` dan di-fit pada train di Phase 5. Test set tidak boleh dipakai untuk seleksi model.

## 4. Kebijakan data sintetis dan nyata

| Aturan | Penegakan |
|---|---|
| Sumber menentukan jenis | `--source simulator` selalu `synthetic`. `android` selalu `real` |
| Folder terpisah | Sesi `synthetic` di `real/`, atau sebaliknya, ditolak V06 |
| Penanda | Nama `SYNTHETIC_`, file penanda, dan `data_kind` |
| Tidak tercampur | Build dan split menolak campuran |
| Laporan | Laporan kualitas dan split menampilkan peringatan SINTETIS |
| Klaim | `evaluation_ready` selalu salah untuk data sintetis |

Profil getaran pada generator adalah angka buatan. Data sintetis hanya membuktikan bahwa perangkat lunak berjalan. Model atau skor dari data ini tidak boleh disebut performa deteksi.
