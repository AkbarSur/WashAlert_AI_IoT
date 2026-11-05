# Artefak model

| Folder | Isi |
|---|---|
| `development/` | Model hasil training. Nama `SYNTHETIC_*` berarti dilatih dengan data buatan dan **bukan** bukti performa |
| `production/` | Kosong. Hanya untuk model data nyata yang lulus evaluasi held-out dan disetujui kelompok |

File `.joblib` dapat menjalankan kode saat dimuat. Muat hanya artefak buatan sendiri, setelah hash diperiksa oleh `nodes/detector_service/inference.py`.

## Provenance artefak yang dilacak

`development/SYNTHETIC_syn_hard_v1-v1-decision_tree-F2-624d6645`: dilatih dengan `ml.train` dari `syn_hard_v1` (data generator, seed 42), split `v1`, scikit-learn 1.9.1, Python 3.13. Hash file, hash dataset, fitur, dan hasil ada di `metadata.json`. Dibangun ulang dari salinan bersih pada 5 November 2026 dengan hasil identik byte per byte. Hanya untuk uji perangkat lunak dan demo.
