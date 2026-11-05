# Dataset WashAlert AI

| Folder | Isi | Boleh untuk klaim performa |
|---|---|---|
| `real/` | Rekaman nyata dari HP A, sumber `android` | Ya, setelah validasi dan evaluasi |
| `synthetic/` | Data buatan generator atau simulator | **Tidak pernah** |
| `processed/` | Hasil `ml.build_dataset`, dapat dibangun ulang | Mengikuti `data_kind` |
| `manifests/` | Split yang dikunci | Mengikuti `data_kind` |

Saat ini `real/` kosong: **belum ada data nyata yang dikumpulkan.**

Jangan memindahkan sesi antar folder. Validator menolak sesi yang `data_kind`-nya tidak cocok.
Panduan: `docs/data_collection_guide.md` dan `docs/labeling_protocol.md`.
