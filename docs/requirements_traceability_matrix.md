# Requirements Traceability Matrix: WashAlert AI

Versi 0.7, mengikuti SRS v0.7, setelah Phase 8, 5 November 2026. Status IT Phase 6 berarti teruji perangkat lunak dengan broker lokal atau simulasi, bukan pada HP dan mesin cuci. Semua hasil ML sejauh ini memakai data sintetis.

## Ringkasan

| Kelompok | Total | Must | Should | Could | Existing and verified | Existing but not verified | Planned | Implemented but not tested | Implemented and tested | Butuh data nyata |
|---|---|---|---|---|---|---|---|---|---|---|
| Fungsional | 87 | 69 | 17 | 1 | 23 | 5 | 2 | 4 | 53 | 9 |
| Non-fungsional | 29 | 18 | 9 | 2 | 2 | 5 | 7 | 2 | 13 | 5 |
| Data dan ML | 27 | 22 | 4 | 1 | 0 | 0 | 1 | 6 | 20 | 8 |
| **Total** | 143 | 109 | 30 | 4 | 25 | 10 | 10 | 12 | 86 | 22 |

**Uji fisik = Belum** berarti kebutuhan itu masih harus dibuktikan di HP, mesin, atau rekaman nyata. Status "Implemented and tested" hanya berarti test perangkat lunak lulus.

## Definisi status

| Status | Arti |
|---|---|
| Existing and verified | Ada pada kode lama dan terbukti lewat test atau uji audit pada simulator, mock, atau broker lokal |
| Existing but not verified | Ada pada kode lama, tetapi belum terbukti secara memadai, misalnya butuh HP nyata |
| Planned | Belum diimplementasikan |
| Implemented but not tested | Sudah ditulis, tetapi kriteria penerimaannya belum dapat diuji, misalnya butuh HP nyata atau Phase 5 |
| Implemented and tested | Sudah ditulis dan test perangkat lunak lulus, dengan mock, simulator, atau broker lokal |

## Keterangan test

- `test_*`: test yang ada di repository lama.
- `AUDIT-*`: uji yang dijalankan saat audit dan belum berada di repository.
- `TC-*`: test case yang direncanakan, belum ada. Akhiran `-HP`, `-LAPANGAN`, `-G1`, dan `-TRAIN` menandai bukti yang masih menunggu HP, lapangan, gerbang G1, atau Phase 5.

## Matriks

| ID | Kebutuhan | Sumber / rasional | Prioritas | Komponen | Verifikasi | Test case | Status | Uji fisik |
|---|---|---|---|---|---|---|---|---|
| FR-001 | Pembacaan accelerometer dan gyroscope | D-IOT ketentuan 2; C `sensors.py` | Must | `shared/sensors.py` | Demo | TC-FR-001 | Existing but not verified | Belum |
| FR-002 | Deteksi nama sensor | C `sensors.py`; presentasi lama (kendala 1) | Must | `shared/sensors.py` | Uji (mock), Demo | test_detects_vendor_sensor_names_and_skips_uncalibrated, test_env_override_wins, test_missing_sensor_lists_available_names | Implemented and tested | - |
| FR-003 | Penandaan sampel basi | A-08 (uji mock) | Must | `shared/sensors.py`, `shared/features.py` | Uji | test_missing_gyro_is_marked_not_zero_filled, test_stale_samples_counted | Implemented and tested | - |
| FR-004 | Deteksi sensor gagal | A-08 | Must | `shared/sensors.py`, `shared/edge_runner.py` | Uji | test_sensor_fault_after_repeated_empty_reads_and_recovery, test_sensor_fault_recorded_in_metadata | Implemented and tested | - |
| FR-005 | Waktu dan laju nyata | PI §8; A-09 | Must | `shared/features.py` | Uji | test_actual_rate_from_timestamps_not_nominal, test_irregular_sampling_uses_real_duration | Implemented and tested | - |
| FR-006 | Alat ukur sampling | PI §8; A-09 | Must | `ml/measure_sampling.py` | Demo, Uji (mock) | test_summary_from_timestamps, test_stream_probe_counts_objects, test_measure_tool_reports_rate_and_stream_probe, TC-FR-006-HP | Implemented but not tested | Belum |
| FR-007 | Pemanfaatan semua sampel | A-07 (uji mock) | Should | `shared/sensors.py` | Uji, Inspeksi | TC-FR-007 | Planned | Belum |
| FR-008 | Processing A: motion_rms | D-IOT ketentuan 3; C `processing.py`; PI §18.8 | Must | `shared/processing.py` | Uji | test_stationary_phone, test_movement_increases_features, test_need_multiple_samples | Existing and verified | - |
| FR-009 | Processing B: rotation_rad | D-IOT ketentuan 3; C `processing.py`; PI §18.8 | Must | `shared/processing.py` | Uji | test_stationary_phone, test_movement_increases_features | Existing and verified | - |
| FR-010 | Fitur getaran tanpa offset | A-03, A-04, A-05 (uji) | Must | `shared/features.py` | Uji | test_acc_dyn_rms_sees_horizontal_and_vertical_equally, test_offset_does_not_change_acc_dyn_rms, test_gyro_rms_independent_of_window_length | Implemented and tested | - |
| FR-011 | Moving average | C `rules.py`; PI §8 | Must | `rules.py` | Uji | test_short_bump_does_not_start, test_status_payload_fields | Existing and verified | - |
| FR-012 | Timer durasi | C `rules.py`; PI §8 | Must | `rules.py` | Uji | test_full_cycle_reaches_done_once | Existing and verified | - |
| FR-013 | Sampel tidak valid | PI §8, §14; A-09 | Must | `shared/features.py`, `shared/edge_runner.py` | Uji | test_nan_and_infinity_rejected, test_backward_timestamp_gives_no_negative_values | Implemented and tested | - |
| FR-014 | Fitur frekuensi bersyarat | PI §8; A-09 | Could | `shared/features.py`, `ml/train.py` | Analisis | TC-FR-014 | Planned | Belum |
| FR-015 | Publikasi telemetri | D-IOT ketentuan 5; C `edge_runner.py` | Must | `shared/edge_runner.py` | Uji, Demo | test_edge_starts_before_broker_and_telemetry_is_v2, test_full_cycle_alert_and_ack_unchanged | Existing and verified | - |
| FR-016 | Telemetri v2 kompatibel | PI §12 | Must | `shared/messages.py` | Uji | test_v1_payload_still_accepted_and_has_no_extra, test_v2_round_trip_keeps_old_fields, test_detector_behaves_same_for_v1_and_v2 | Implemented and tested | - |
| FR-017 | Validasi skema | C `messages.py`, `main.py`; PI §12 | Must | `shared/messages.py` | Uji | test_malformed_values_rejected, test_missing_v1_field_rejected, test_invalid_v2_field_rejected | Implemented and tested | - |
| FR-018 | Kecocokan topik dan device | C `main.py`; PI §14 | Must | `nodes/detector_service/main.py` | Uji | TC-FR-018 | Existing but not verified | - |
| FR-019 | Penolakan pesan basi | C `rules.py`; PI §10 | Must | `rules.py` | Uji | test_replay_and_stale_rejected | Existing and verified | - |
| FR-020 | Penolakan replay | C `rules.py`; PI §10 | Must | `rules.py` | Uji | test_replay_and_stale_rejected | Existing and verified | - |
| FR-021 | Penolakan terlihat | A-15 (uji) | Should | `nodes/detector_service/main.py` | Uji | test_status_carries_mode_and_sensor, test_replay_counted_and_status_rate_limited | Implemented and tested | - |
| FR-022 | Edge tahan putus koneksi | A-01 (uji); PI §11 | Must | `shared/edge_runner.py` | Uji | test_edge_survives_three_broker_restarts, test_not_connected_drops_without_exception, test_publish_error_does_not_raise | Implemented and tested | - |
| FR-023 | Retry koneksi awal | A-02 (uji); PI §11 | Should | `shared/mqtt_connection.py` | Uji | test_edge_starts_before_broker_and_telemetry_is_v2, test_detector_starts_before_broker | Implemented and tested | - |
| FR-024 | Perekaman sampel mentah | PI §7; D-AI slide 35 | Must | `ml/record_session.py` | Uji, Demo | test_writes_schema_and_counts, test_record_then_validate_as_real_source_path, TC-FR-024-HP | Implemented and tested | Belum |
| FR-025 | Identitas sesi | PI §7 | Must | `ml/record_session.py` | Uji | test_invalid_arguments, test_full_name_in_metadata_rejected | Implemented and tested | - |
| FR-026 | Pelabelan observasi | PI §7; D-AI slide 33, 38 | Must | `ml/label_session.py`, `docs/labeling_protocol.md` | Demo, Inspeksi | test_interactive_labels_close_previous_interval, test_import_events_from_video, test_offset_from_tap_peak, TC-FR-026-LAPANGAN | Implemented and tested | Belum |
| FR-027 | Pencegahan rekaman tercampur | PI §7 | Must | `ml/record_session.py` | Uji | test_refuses_to_overwrite_session, test_labels_not_overwritten | Implemented and tested | - |
| FR-028 | Validator dataset | PI §7; D-AI slide 37–39 | Must | `ml/validate_dataset.py` | Uji | test_single_bad_row_quarantined_not_imputed, test_out_of_order_rejected_not_sorted, test_unknown_label_rejected, test_cli_exit_codes | Implemented and tested | - |
| FR-029 | Ekspor dataset jendela | PI §7, §8 | Must | `ml/build_dataset.py`, `shared/features.py` | Uji | test_deterministic, test_windows_near_label_change_excluded | Implemented and tested | - |
| FR-030 | Pemisahan data sintetis | PI §7, §18 | Must | `ml/validate_dataset.py`, `ml/generate_synthetic.py` | Uji | test_marked_and_accepted, test_real_and_synthetic_cannot_mix, test_refuses_other_folders, test_rejected_when_placed_in_real_folder | Implemented and tested | - |
| FR-031 | Perintah training | PI §5, §6, §9; D-AI slide 25 | Must | `ml/train.py` | Uji | test_baselines_and_candidates_present, test_experiment_recorded, test_mixed_dataset_rejected | Implemented and tested | - |
| FR-032 | Perintah evaluasi | PI §9, §15 | Must | `ml/evaluate.py` | Uji | test_results_and_synthetic_warning, test_second_evaluation_refused_and_access_logged | Implemented and tested | - |
| FR-033 | Artefak model | PI §6, §9 | Must | `ml/train.py` | Uji | test_metadata_complete, test_round_trip_matches_training_path | Implemented and tested | - |
| FR-034 | Pemuatan model aman | PI §11; A-18 | Must | `nodes/detector_service/inference.py` | Uji | test_tampered_file_not_deserialized, test_model_missing, test_feature_schema_mismatch, test_corrupt_model_with_matching_hash | Implemented and tested | - |
| FR-035 | Prediksi aktivitas | PI §5; D-AI slide 25 | Must | `nodes/detector_service/inference.py` | Uji | test_model_used_when_confident, test_hybrid_synthetic_model_runs_end_to_end | Implemented and tested | - |
| FR-036 | Agregasi jendela | PI §8, §11 | Must | `nodes/detector_service/activity.py` | Uji | test_incomplete_window, test_hybrid_synthetic_model_runs_end_to_end | Implemented and tested | - |
| FR-037 | Publikasi hasil prediksi | PI §12, §13 | Must | `shared/messages.py`, `main.py` | Uji | test_status_carries_mode_and_sensor, test_hybrid_synthetic_model_runs_end_to_end | Implemented and tested | - |
| FR-038 | Mode deteksi | PI §11, prompt Phase 6 §6 | Must | `nodes/detector_service/main.py` | Uji | test_rule_only_default_without_model, test_ml_only_runs_without_window_fallback, test_unknown_mode_refused_at_start, test_ml_only_without_model_reports_rule_only_and_cycle_works | Implemented and tested | - |
| FR-039 | Default kompatibel | PI §11, §18 | Must | `nodes/detector_service/main.py` | Uji | test_default_is_rule_only, test_rule_only_full_cycle, test_constructor_defaults_preserve_old_behaviour | Implemented and tested | - |
| FR-040 | Pemisahan aktivitas dan keputusan | PI §5, §10 | Must | `rules.py`, `activity.py` | Uji, Inspeksi | test_probability_never_decides_done_directly, test_model_reaches_fsm_only_through_activity_module | Implemented and tested | - |
| FR-041 | Probabilitas rendah | PI §11 | Must | `activity.py` | Uji | test_low_probability_uses_rule | Implemented and tested | - |
| FR-042 | Smoothing prediksi | PI §10 | Must | `activity.py` | Uji | test_smoothing_rejects_single_flip | Implemented and tested | - |
| FR-043 | Toleransi offset | A-05 (uji) | Must | `activity.py`, `ml/` | Uji, Analisis | test_offset_does_not_block_done_in_hybrid, TC-FR-043-HP | Implemented but not tested | Belum |
| FR-044 | State siklus | D-IOT ketentuan 4; C `rules.py`; PI §10 | Must | `rules.py` | Uji | test_full_cycle_reaches_done_once | Existing and verified | - |
| FR-045 | Senggolan singkat | C `rules.py`; PI §14 | Must | `rules.py` | Uji | test_short_bump_does_not_start | Existing and verified | - |
| FR-046 | Independen dari periode telemetri | A-13 (uji) | Must | `rules.py` | Uji | test_single_bump_ignored_at_any_period, test_single_bump_does_not_start | Implemented and tested | - |
| FR-047 | Jeda singkat | C `rules.py`; PI §14 | Must | `rules.py` | Uji | test_short_pause_is_not_done | Existing and verified | - |
| FR-048 | Syarat durasi minimum | A-11 (uji) | Must | `rules.py` | Uji | test_short_run_never_alerts | Implemented and tested | Belum |
| FR-049 | Batas diam berbasis data | A-10 (uji); PI §10 | Must | `rules.py`, `ml/evaluate.py` | Analisis, Uji | test_pause_analysis_ignores_idle_outside_cycle, TC-FR-049-LAPANGAN | Implemented but not tested | Belum |
| FR-050 | Alasan selesai | A-11 | Should | `rules.py` | Uji | test_after_spin_uses_done_s, test_without_spin_waits_longer_and_says_so | Implemented and tested | - |
| FR-051 | Koreksi saat mesin aktif lagi | A-10, A-12 (uji) | Must | `rules.py` | Uji | test_correction_after_false_done, test_brief_bump_in_done_is_not_correction, test_correction_clear_precedes_alert | Implemented and tested | - |
| FR-052 | Alert sekali per penyelesaian | C `rules.py`; PI §10 | Must | `rules.py` | Uji | test_full_cycle_reaches_done_once | Existing and verified | - |
| FR-053 | Stabilitas SPIN | A-14 (uji) | Should | `rules.py` | Uji | test_rotation_needs_consecutive_windows, test_rotation_streak_broken_by_stillness | Implemented and tested | - |
| FR-054 | Watchdog HP A | A-17; PI §11 | Must | `nodes/detector_service/main.py`, `rules.py` | Uji | test_sensor_lost_mid_cycle_is_not_done, test_lost_in_done_stays_done_reminds_and_ack_works, test_sensor_lost_published_by_tick | Implemented and tested | - |
| FR-055 | Pemulihan state | A-19 | Should | `nodes/detector_service/state_store.py` | Uji | test_done_survives_restart_and_reminder_continues, test_corrupt_or_old_state_is_ignored, test_detector_restart_restores_done | Implemented and tested | - |
| FR-056 | Publikasi alert | C `main.py`; PI §12 | Must | `nodes/detector_service/main.py` | Uji, Demo | test_full_cycle_alert_and_ack_unchanged | Existing and verified | - |
| FR-057 | Pengingat | C `rules.py` | Must | `rules.py` | Uji | test_reminder_then_owner_ack | Existing and verified | - |
| FR-058 | Alarm HP B | C `alarm.py`; presentasi lama | Must | `shared/alarm.py` | Uji (mock), Demo | test_android_vibrates_and_notifies, test_laptop_only_prints, TC-FR-058-HP | Existing but not verified | Belum |
| FR-059 | Validasi alert | A-20 (uji); PI §12 | Must | `shared/messages.py`, `shared/edge_runner.py` | Uji | test_rejects_bad, test_rejects_expired, test_malformed_ignored | Implemented and tested | - |
| FR-060 | Alert ID dan dedupe | PI §10, §14 | Should | `shared/messages.py`, `shared/edge_runner.py` | Uji | test_dedupes_same_id, test_reminder_with_new_id_rings | Implemented and tested | - |
| FR-061 | Alert setelah HP B offline | A-21 (uji) | Should | `nodes/detector_service/main.py`, `shared/edge_runner.py` | Uji | test_alert_state_retained_for_late_subscriber, test_retained_state_catches_up_once | Implemented and tested | - |
| FR-062 | Alarm tidak menahan MQTT | A-22 | Should | `shared/alarm.py`, `shared/edge_runner.py` | Uji | test_slow_alarm_does_not_block_mqtt_thread, test_alarm_failure_does_not_escape | Implemented and tested | - |
| FR-063 | Konfirmasi goyang | C `rules.py`; presentasi lama | Must | `rules.py` | Uji | test_reminder_then_owner_ack | Existing and verified | - |
| FR-064 | Goyangan di luar DONE diabaikan | C `rules.py` | Must | `rules.py` | Uji | test_owner_shake_ignored_while_washing | Existing and verified | - |
| FR-065 | Konfirmasi tahan guncangan | A-23 (uji) | Must | `rules.py` | Uji | test_single_shake_not_enough, test_shake_streak_broken, test_two_shakes_clear_alert_and_new_cycle_can_start | Implemented and tested | - |
| FR-066 | Umpan balik konfirmasi | A-24; PI §12 | Should | `main.py`, `shared/alarm.py` | Uji (mock), Demo | test_ack_clears_state, test_inactive_clears_only_after_active | Implemented and tested | - |
| FR-067 | Perintah ARM dan DISARM | C `main.py`, `rules.py`; D-IOT contoh dashboard | Must | `rules.py`, `main.py` | Uji | test_disarm_resets, AUDIT-DASH | Existing and verified | - |
| FR-068 | Kontrol dari CLI dan penolakan perintah | C `send_control.py`, `main.py` | Should | `send_control.py`, `main.py` | Uji | TC-FR-068 | Existing but not verified | - |
| FR-069 | Status ARM akurat | A-25 | Should | `main.py` | Uji | test_arm_reports_true_state, test_reconnect_reports_true_state | Implemented and tested | - |
| FR-070 | Status utama | C `index.html`; D-IOT ketentuan 6 | Must | `dashboard/index.html` | Uji | test_03_valid_telemetry_and_05_chart_updates, test_16_arm_and_17_disarm_confirmed_by_detector, test_timeline_shows_recorded_path_only_and_idle_is_not_done | Existing and verified | - |
| FR-071 | Grafik getaran | C `index.html` | Must | `dashboard/index.html` | Uji, Inspeksi | test_03_valid_telemetry_and_05_chart_updates, test_chart_breaks_line_across_gap_and_marks_it | Existing and verified | - |
| FR-072 | Koneksi dan kontrol | C `index.html` | Must | `dashboard/index.html` | Uji | test_11_mqtt_disconnected_and_12_reconnected, test_16_arm_and_17_disarm_confirmed_by_detector, test_18_command_timeout_does_not_change_status, test_18b_command_fails_when_disconnected | Existing and verified | - |
| FR-073 | Konfigurasi tanpa kredensial | C `dashboard_server.py` | Must | `shared/dashboard_server.py` | Uji | test_local_http_server_and_no_credentials, test_private_broker_does_not_expose_password | Existing and verified | - |
| FR-074 | Panel model | PI §11, §13 | Must | `dashboard/index.html` | Uji | test_06_ml_prediction_rendered_without_confidence_label, test_07_unknown_model_status, test_08_rule_only, test_09_hybrid_fallback_is_visible, test_10_synthetic_and_simulation_markers | Implemented and tested | - |
| FR-075 | Istilah probabilitas | PI §13 | Must | `dashboard/index.html` | Inspeksi | test_06_ml_prediction_rendered_without_confidence_label | Implemented and tested | - |
| FR-076 | Kualitas sensor | PI §13; A-08 | Should | `dashboard/index.html` | Uji | test_sensor_v1_and_fault_differ, test_13_stale_then_offline_sensor | Implemented and tested | - |
| FR-077 | Penjelasan dan riwayat | PI §13 | Should | `dashboard/index.html` | Uji | test_14_alert_received_and_15_acknowledged, test_timeline_shows_recorded_path_only_and_idle_is_not_done, test_history_is_bounded | Implemented and tested | - |
| FR-078 | Tanpa metrik rekaan | PI §13, §18 | Must | `dashboard/index.html` | Inspeksi | test_no_secret_or_inline_handlers_or_fixed_metrics_in_source | Implemented and tested | - |
| FR-079 | Simulator sensor | C `sensors.py`, README | Must | `shared/sensors.py` | Uji | test_full_cycle_alert_and_ack_unchanged, test_simulator_samples_are_fresh | Existing and verified | - |
| FR-080 | Demo offline | C `offline_demo.py` | Should | `scripts/offline_demo.py` | Uji | test_offline_demo_still_runs | Existing and verified | - |
| FR-081 | Pemutaran ulang rekaman | PI §15 | Must | `ml/replay.py` | Uji | test_replay_deterministic, test_arms_replay_runs_through_production_rules | Implemented and tested | - |
| FR-082 | Skenario regresi | PI §14; A-01 sampai A-30 | Must | `tests/` | Uji, Inspeksi | test_rules_has_no_mqtt_dependency, test_noisy_flips_do_not_finish, TC-FR-082-AUDIT | Implemented but not tested | - |
| FR-083 | Fallback model | PI §11 | Must | `inference.py`, `main.py` | Uji | test_hybrid_missing_model_falls_back_and_cycle_still_works, test_corrupted_model_falls_back, test_missing_dependency_falls_back, test_model_failure_disables_and_status_can_say_so, test_runtime_model_failure_visible_in_status | Implemented and tested | - |
| FR-084 | Fitur tidak valid saat inference | PI §11, §14 | Must | `inference.py`, `activity.py` | Uji | test_v1_telemetry_falls_back_visibly, test_out_of_range_uses_rule, test_sensor_fault_cannot_cause_false_done | Implemented and tested | - |
| FR-085 | Kegagalan callback | A-26; PI §11 | Should | `nodes/detector_service/main.py` | Uji | test_exception_in_handler_does_not_propagate, test_bad_payload_counted_not_fatal | Implemented and tested | - |
| FR-086 | Detector tersambung kembali | C `main.py` | Must | `nodes/detector_service/main.py` | Uji | test_detector_resubscribes_after_broker_restart | Existing and verified | - |
| FR-087 | Status offline | C `main.py`, `mqtt_connection.py` | Should | `main.py`, `mqtt_connection.py` | Uji | TC-FR-087 | Existing but not verified | - |
| NFR-001 | Latensi inference | PI §6 | Should | `inference.py` | Uji | test_latency_measured, test_too_slow_model_excluded | Implemented and tested | - |
| NFR-002 | Latensi status | PI §15; D-IOT | Should | `main.py` | Uji | test_rule_only_full_cycle, TC-NFR-002 terukur pada reports/e2e/phase7 | Implemented and tested | - |
| NFR-003 | Latensi notifikasi | PI §15 | Should | Sistem | Demo | TC-NFR-003 | Planned | Belum |
| NFR-004 | Keterlambatan deteksi selesai | PI §9, §15 | Must | `ml/evaluate.py` | Analisis | TC-NFR-004 | Planned | Belum |
| NFR-005 | Pemulihan koneksi | A-01; PI §11 | Must | `edge_runner.py` | Uji | test_edge_survives_three_broker_restarts | Implemented and tested | - |
| NFR-006 | Uji ketahanan | PI §14 | Should | Sistem | Uji | TC-NFR-006 pada reports/soak | Implemented and tested | - |
| NFR-007 | Alert palsu | PI §9, §15; A-10 | Must | `ml/evaluate.py` | Analisis | TC-NFR-007 | Planned | Belum |
| NFR-008 | Alert terlewat | PI §9, §15 | Must | `ml/evaluate.py` | Analisis | TC-NFR-008 | Planned | Belum |
| NFR-009 | Kerahasiaan kredensial | PI §12, §18 | Must | `Repository`, `dashboard_server.py` | Inspeksi, Uji | test_local_http_server_and_no_credentials, test_no_private_paths_or_credentials | Existing and verified | - |
| NFR-010 | TLS default | D-IOT tutorial; C `mqtt_connection.py` | Must | `mqtt_connection.py` | Uji | TC-NFR-010 | Existing but not verified | - |
| NFR-011 | Broker berautentikasi | A-27 (uji), A-06; D-IOT tabel broker | Should | `mqtt_connection.py`, `index.html` | Uji | test_credentials_form_stays_in_memory, test_private_broker_does_not_expose_password, TC-NFR-011-BROKER | Implemented but not tested | - |
| NFR-012 | Data minimal | D-IOT slide broker; PI §12 | Must | `shared/messages.py` | Inspeksi | test_payloads_hold_no_personal_fields | Implemented and tested | - |
| NFR-013 | Pemuatan model aman | A-18 | Must | `inference.py` | Uji | test_tampered_file_not_deserialized, test_model_missing, test_feature_schema_mismatch, test_corrupt_model_with_matching_hash | Implemented and tested | - |
| NFR-014 | Fungsi inti tanpa ML | PI §11 | Must | Sistem | Uji | test_core_runs_without_ml_or_mqtt_packages, test_rule_only_full_cycle | Implemented and tested | - |
| NFR-015 | State saat broker putus | PI §11 | Must | `main.py` | Uji | test_cycle_state_survives_broker_restart | Implemented and tested | - |
| NFR-016 | Inti tanpa MQTT | C `rules.py` | Must | `rules.py`, `activity.py` | Uji, Inspeksi | test_rules_has_no_mqtt_dependency, TC-NFR-016 | Existing but not verified | - |
| NFR-017 | Regresi test lama | PI §18 | Must | `tests/` | Uji | 15 test lama | Existing and verified | - |
| NFR-018 | Definisi fitur tunggal | PI §8 | Must | `shared/features.py` | Uji | test_dataset_and_runtime_paths_match | Implemented and tested | - |
| NFR-019 | Keterlacakan test | PI §22 | Should | `tests/` | Inspeksi | TC-NFR-019 | Planned | - |
| NFR-020 | Pemahaman dashboard | PI §13 | Could | index.html | Demo | TC-NFR-020 | Planned | - |
| NFR-021 | Lebar layar | PI §13 | Should | index.html | Uji | test_20_responsive_no_horizontal_scroll | Implemented and tested | - |
| NFR-022 | Panduan penyiapan | PI §16 | Should | README.md | Demo | test_readme_modules_and_files_exist, TC-NFR-022-KELOMPOK | Implemented but not tested | - |
| NFR-023 | Kebutuhan edge ringan | D-IOT tutorial; C `requirements.txt` | Must | `shared/`, `hp_*.py` | Uji, Demo | test_edge_still_has_no_ml_dependency, test_recorder_does_not_need_mqtt_or_numpy, TC-NFR-023-HP | Existing but not verified | Belum |
| NFR-024 | Sistem operasi laptop | C README | Should | Laptop | Uji | TC-NFR-024 | Existing but not verified | - |
| NFR-025 | Lingkup kapasitas | Presentasi lama (pengembangan masa depan) | Must | Sistem | Inspeksi | TC-NFR-025 | Existing but not verified | - |
| NFR-026 | Memori terbatas | A-28 | Could | `rules.py` | Uji | TC-NFR-026 | Planned | - |
| NFR-027 | Training berulang | PI §9 | Must | `ml/train.py` | Uji | test_reproducible_with_same_seed | Implemented and tested | - |
| NFR-028 | Dependensi tercatat | PI §9 | Must | requirements-ml.txt | Inspeksi | test_metadata_complete, test_dependency_mismatch | Implemented and tested | - |
| NFR-029 | Label bukti pada hasil | PI §14, §18 | Must | Dokumen | Inspeksi | test_synthetic_marked_in_name_and_metadata, test_synthetic_never_claims_validation | Implemented and tested | - |
| DML-001 | Skema data mentah | PI §7 | Must | `ml/validate_dataset.py` | Uji | test_writes_schema_and_counts, test_wrong_columns_rejected | Implemented and tested | - |
| DML-002 | Skema sesi dan label | PI §7 | Must | `ml/validate_dataset.py` | Uji | test_missing_files_rejected, test_corrupt_meta_rejected | Implemented and tested | - |
| DML-003 | Definisi kelas | PI §5; D-AI slide 45 | Must | `docs/labeling_protocol.md` | Inspeksi, Uji | test_done_is_not_a_sensor_label, test_unknown_label_rejected | Implemented and tested | - |
| DML-004 | Zona transisi dan label ragu | PI §7; D-AI slide 38, 45 | Must | `ml/build_dataset.py` | Uji | test_windows_near_label_change_excluded, test_uncertain_never_reaches_training | Implemented and tested | - |
| DML-005 | Kelas tambahan bersyarat | PI §5 | Could | `ml/` | Analisis | TC-DML-005 | Planned | Belum |
| DML-006 | Protokol pelabelan | PI §7; D-AI slide 33, 38 | Must | `docs/labeling_protocol.md` | Inspeksi | TC-DML-006-LAPANGAN | Implemented but not tested | Belum |
| DML-007 | Validasi kualitas data | PI §7, §8 | Must | `ml/build_dataset.py` | Uji | test_stale_windows_excluded, test_gap_drops_affected_edge_window, test_builds_labeled_windows_and_reports | Implemented and tested | - |
| DML-008 | Daftar fitur | PI §5, §8 | Must | `shared/features.py` | Uji | test_acc_dyn_rms_sees_horizontal_and_vertical_equally, test_statistics_correct, test_feature_order_fixed | Implemented and tested | - |
| DML-009 | Jendela agregat | PI §8 | Must | `shared/features.py` | Uji, Analisis | test_boundary_window_excluded_exactly_at_limit, test_not_ready_when_coverage_too_short, test_uses_only_past_windows, TC-DML-009-G1 | Implemented but not tested | Belum |
| DML-010 | Urutan fitur | PI §8 | Must | `inference.py` | Uji | test_feature_order_is_taken_from_metadata, test_feature_schema_mismatch | Implemented and tested | - |
| DML-011 | Split per siklus | PI §9; D-AI slide 45 | Must | `ml/train.py` | Uji | test_no_group_in_two_parts, test_row_level_split_would_be_detected | Implemented and tested | - |
| DML-012 | Kunci test set | PI §9 | Must | `data/manifest` | Inspeksi | test_locked_split_not_overwritten, test_verify_detects_changed_dataset, TC-DML-012-LAPANGAN | Implemented and tested | Belum |
| DML-013 | Cross-validation kelompok | PI §9 | Should | `ml/train.py` | Uji | test_folds_are_group_aware, test_cv_folds_leave_one_cycle_out_exclude_test, test_too_few_groups_refused | Implemented and tested | - |
| DML-014 | Kecukupan data | PI §9; D-AI slide 45 | Must | Laporan | Inspeksi | test_few_cycles_warn, test_synthetic_never_marked_evaluation_ready, test_real_data_with_enough_cycles_can_be_ready | Implemented and tested | Belum |
| DML-015 | Baseline | PI §6, §15 | Must | `ml/train.py` | Uji | test_baselines_and_candidates_present, test_threshold_baseline_is_not_labelled_as_ml, test_rule_mapping | Implemented and tested | - |
| DML-016 | Kandidat dan seleksi | PI §6; D-AI slide 46 (scikit-learn terdaftar) | Must | `ml/train.py` | Uji, Inspeksi | test_clear_winner_selected, test_simpler_model_wins_tie, test_too_slow_model_excluded, test_baseline_never_selected | Implemented and tested | - |
| DML-017 | Metrik aktivitas | PI §9 | Must | `ml/evaluate.py` | Uji | test_values_calculated_by_hand, test_majority_shows_why_accuracy_is_not_enough | Implemented and tested | - |
| DML-018 | Metrik siklus | PI §9, §15 | Must | `ml/evaluate.py` | Uji | test_completion_metrics, test_arms_replay_runs_through_production_rules, TC-DML-018-LAPANGAN | Implemented but not tested | - |
| DML-019 | Ketidakseimbangan kelas | PI §9 | Must | `ml/train.py` | Inspeksi | test_majority_shows_why_accuracy_is_not_enough, test_results_and_synthetic_warning | Implemented and tested | - |
| DML-020 | Perbandingan empat kelompok | PI §15 | Must | `ml/evaluate.py`, `ml/replay.py`, `ml/baselines/legacy_rules.py` | Analisis | test_legacy_rules_is_frozen_copy, test_arms_replay_runs_through_production_rules, TC-DML-020-LAPANGAN | Implemented but not tested | Belum |
| DML-021 | Generalisasi bersyarat | PI §9 | Should | `ml/evaluate.py` | Analisis | test_holdout_machine_only_in_test, TC-DML-021-LAPANGAN | Implemented but not tested | Belum |
| DML-022 | Metadata model | PI §9 | Must | `ml/train.py` | Uji | test_metadata_complete | Implemented and tested | - |
| DML-023 | Versioning | PI §9 | Must | `inference.py` | Uji | test_reproducible_with_same_seed, test_feature_schema_mismatch | Implemented and tested | - |
| DML-024 | Ambang probabilitas | PI §11 | Should | `ml/train.py` | Analisis | test_threshold_rule, test_low_probability_flag, TC-DML-024-LAPANGAN | Implemented but not tested | Belum |
| DML-025 | Kalibrasi | PI §13 | Must | Laporan | Inspeksi | test_calibration_error, test_metadata_complete | Implemented and tested | - |
| DML-026 | Pernyataan batasan | PI §9; D-AI slide 45 | Must | Laporan | Inspeksi | test_results_and_synthetic_warning, test_synthetic_never_claims_validation | Implemented and tested | - |
| DML-027 | Penyimpanan data pribadi | A-29 | Should | `data/` | Inspeksi | test_full_name_in_metadata_rejected | Implemented and tested | - |
