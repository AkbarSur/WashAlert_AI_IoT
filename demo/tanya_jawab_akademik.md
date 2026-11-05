# Persiapan Tanya Jawab

Semua angka berasal dari data sintetis, kecuali yang disebut lain. Jika pertanyaan melewati isi dokumen ini, jawab tidak tahu lalu sebut cara mengeceknya.

**1. Mengapa memakai machine learning?**
Audit menunjukkan ambang tetap rapuh: offset 0,15 m/s² mencegah DONE, dan getaran horizontal hampir tidak terbaca `motion_rms`. Model dapat memakai beberapa fitur sekaligus. Namun ini masih hipotesis, karena belum diuji pada mesin nyata.

**2. Mengapa tidak cukup threshold?**
Bisa jadi cukup. Threshold mudah dijelaskan dan tetap menjadi default. Kelemahannya, nilainya sensitif terhadap HP, posisi, dan mesin. Jika pada data nyata model tidak lebih baik, kami memakai `RULE_ONLY` dengan FSM baru.

**3. Apa beda AI dengan algoritma berbasis aturan?**
Pada aturan, manusia menulis ambangnya. Pada supervised learning, pola dipelajari dari data berlabel lewat training, menghasilkan artefak `model.joblib`. FSM kami tetap aturan, jadi bukan ML.

**4. Bagian mana yang benar-benar AI?**
Hanya classifier aktivitas pada `HYBRID` dan `ML_ONLY`. Sisanya aturan deterministik.

**5. Mengapa memilih decision tree?**
Aturan pemilihan ditetapkan lebih dulu: macro-F1 CV tertinggi, selisih ≤ 0,01 memilih yang lebih sederhana, dan p95 ≤ 100 ms. Decision tree F2 mendapat 0,848, Random Forest F3 0,838. Selisih ini kecil dibanding rentang antar fold 0,670–0,957, jadi pilihan bisa berubah pada data nyata. Decision tree juga jauh lebih kecil: 9 KB dibanding sekitar 1,9 MB.

**6. Bagaimana data dikumpulkan?**
Alatnya tersedia: `ml.measure_sampling`, `ml.record_session`, `ml.label_session`. **Data nyata belum dikumpulkan.** Data saat ini berasal dari `ml.generate_synthetic`, dengan profil yang saya tulis sendiri.

**7. Bagaimana data diberi label?**
Protokolnya pengamatan langsung atau video, dengan pemeriksaan ulang. Label data sintetis dibuat generator, jadi bukan observasi.

**8. Berapa banyak data?**
10 sesi sintetis: 8 siklus dan 2 sesi idle. 3.513 jendela pengembangan dan 1.055 jendela test. Data nyata 0.

**9. Bagaimana mencegah data leakage?**
Split per siklus dan dikunci hash. Grup test dibuang sebelum training. Jendela dekat pergantian label dibuang. Identitas, waktu, dan status FSM tidak masuk fitur. Test hanya dibuka sekali.

**10. Mengapa group-aware splitting?**
Jendela berurutan dari siklus yang sama sangat mirip. Split acak per baris menghasilkan macro-F1 0,948, sedangkan split per siklus 0,848. Selisih itu adalah kebocoran.

**11. Mengapa macro-F1?**
WASHING mendominasi. Baseline yang selalu menebak kelas terbanyak mendapat accuracy 0,673, tetapi macro-F1 hanya 0,268.

**12. Bagaimana menangani class imbalance?**
Memakai macro-F1 dan metrik per kelas, serta baseline mayoritas sebagai pembanding. Kami tidak melakukan oversampling pada data ini.

**13. Bagaimana model menentukan aktivitas?**
Rata-rata, SD, dan maksimum empat fitur dalam 30 detik terakhir masuk ke decision tree. Hasilnya dihaluskan dengan voting mayoritas 5 prediksi sebelum masuk FSM.

**14. Mengapa IDLE tidak sama dengan DONE?**
Mesin yang diam bisa menunggu, jeda, atau selesai. Getarannya sama. Yang membedakan adalah riwayat, jadi keputusan itu milik FSM.

**15. Apa fungsi FSM?**
Melacak siklus, memeriksa durasi kerja minimum dan lama diam, mengirim alert dan pengingat, menangani konfirmasi dan koreksi, serta watchdog HP A.

**16. Bagaimana MQTT dua arah bekerja?**
HP publish telemetri, detector subscribe. Detector publish status, alert, dan `alert_state`. HP B subscribe alert, dashboard subscribe semuanya dan publish `control`. Konfirmasi adalah goyangan pada telemetri HP B.

**17. Apa fungsi HP A dan HP B?**
HP A di atas mesin mengirim getaran. HP B milik pemilik memberi alarm, dan goyangannya menjadi konfirmasi.

**18. Bagaimana false alert dicegah?**
Durasi minimum 600 detik, diam 120 detik atau 240 detik tanpa spin, smoothing, dan syarat mulai dua dari tiga jendela. Data rusak menahan timer. Jika mesin aktif lagi, ada koreksi. Pada 2 siklus test sintetis, alert palsu 0, tetapi data ini terlalu sedikit untuk klaim, dan nilai durasi masih usulan.

**19. Apa yang terjadi jika ML gagal?**
Sistem memakai aturan, `effective_mode` menjadi `RULE_ONLY`, dan alasan tampil di dashboard. Diuji dengan model hilang, file rusak, pustaka hilang, dan galat berulang. Pada `ML_ONLY`, prediksi yang tidak tersedia menahan timer.

**20. Apa kelemahan broker publik?**
Siapa pun yang tahu topiknya dapat membaca dan mengirim, termasuk alert palsu dan DISARM. `PROJECT_ID` bukan autentikasi. Mitigasi: broker berakun dengan ACL. Python sudah mendukung akun, tetapi belum diuji dengan broker berakun nyata.

**21. Bagaimana membuktikan model lebih baik?**
Rekam siklus nyata, kunci split, latih, buka test sekali, lalu bandingkan empat kelompok pada rekaman yang sama: FSM lama, FSM baru dengan aturan, HYBRID, dan ML_ONLY. Ukur alert palsu, alert terlewat, dan keterlambatan.

**22. Apakah sekarang model sudah lebih baik?**
Belum bisa disimpulkan. Pada 2 siklus sintetis, model mendeteksi 1 dari 2 dan aturan 0 dari 2. Data itu dari generator yang sama dengan data latih.

**23. Bagaimana jika model tidak lebih baik?**
Kami melaporkannya dan memakai `RULE_ONLY` dengan FSM baru. Perbaikan keandalan tetap bermanfaat.

**24. Apa keterbatasan dataset?**
Sintetis, satu "mesin", generator ditulis sendiri, RMS diam sengaja di sekitar ambang, dan hanya 2 siklus test. Skor mengikuti cara data dibuat: pada mode mudah mendekati 1,000.

**25. Mengapa skor test (0,920) lebih tinggi dari CV (0,848)?**
Karena dua siklus test kebetulan lebih mudah, bukan karena model lebih baik. Rentang antar fold lebih informatif.

**26. Apakah probabilitas model bisa dipercaya?**
Belum terkalibrasi, dengan ECE 0,141. Karena itu dashboard menyebutnya probabilitas prediksi, bukan confidence.

**27. Apa rencana selanjutnya?**
Uji di HP, ukur laju sampling, rekam minimal 8 siklus, latih ulang, bandingkan empat kelompok, tetapkan `CUCI_DONE_S` dari jeda nyata, dan pakai broker berakun.

**28. Apakah sistem ini sudah diuji di HP?**
Sistem lama pernah terlihat membaca sensor di HP dari satu screenshot. Versi ini belum diuji di HP, dan Termux baru diuji dengan tiruan.
