> **DATA SINTETIS. Hasil ini hanya menguji perangkat lunak, bukan performa pada mesin cuci nyata.**

# Laporan kualitas data: syn_hard_v1

| Ukuran | Nilai |
|---|---|
| data_kind | synthetic |
| sessions_accepted | 10 |
| sessions_rejected | 0 |
| rows_total | 28838 |
| rows_usable | 27986 |
| rows_invalid | 852 |
| rows_quarantined | 0 |
| windows | 4568 |

## Jendela per label

| Label | Jumlah |
|---|---|
| IDLE | 1061 |
| SPIN | 667 |
| WASHING | 2840 |

## Alasan pembuangan

| Alasan | Jumlah |
|---|---|
| agregat_data_kurang | 60 |
| agregat_label_campur_atau_transisi | 1133 |
| edge_sampel_kurang | 7 |
| edge_terlalu_banyak_stale | 2 |

## Per sesi

| Sesi | Status | Median dt (dtk) | Jendela | Temuan |
|---|---|---|---|---|
| SYNTHETIC_IDLE_01 | ACCEPTED | 0.6264 | 175 | V10 MARK_INVALID: Sampel memakai nilai sensor lama |
| SYNTHETIC_IDLE_02 | ACCEPTED | 0.6255 | 175 | V10 MARK_INVALID: Sampel memakai nilai sensor lama |
| SYNTHETIC_SYNM1_C01 | ACCEPTED | 0.6246 | 527 | V10 MARK_INVALID: Sampel memakai nilai sensor lama |
| SYNTHETIC_SYNM1_C02 | ACCEPTED | 0.6242 | 529 | V10 MARK_INVALID: Sampel memakai nilai sensor lama |
| SYNTHETIC_SYNM1_C03 | ACCEPTED | 0.6249 | 526 | V10 MARK_INVALID: Sampel memakai nilai sensor lama |
| SYNTHETIC_SYNM1_C04 | ACCEPTED | 0.6245 | 528 | V10 MARK_INVALID: Sampel memakai nilai sensor lama |
| SYNTHETIC_SYNM1_C05 | ACCEPTED | 0.6252 | 527 | V10 MARK_INVALID: Sampel memakai nilai sensor lama |
| SYNTHETIC_SYNM1_C06 | ACCEPTED | 0.6242 | 526 | V10 MARK_INVALID: Sampel memakai nilai sensor lama |
| SYNTHETIC_SYNM1_C07 | ACCEPTED | 0.625 | 528 | V10 MARK_INVALID: Sampel memakai nilai sensor lama |
| SYNTHETIC_SYNM1_C08 | ACCEPTED | 0.6256 | 527 | V10 MARK_INVALID: Sampel memakai nilai sensor lama |
