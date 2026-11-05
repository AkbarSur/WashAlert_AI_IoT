"""FR telemetri v2 dan validasi skema: kompatibilitas dua arah."""
import json
import unittest

from nodes.detector_service.rules import Config, WasherDetector
from shared.features import compute_window_features, telemetry_extra
from shared.messages import Telemetry
from shared.processing import SensorSample

V1 = {"device_id": "edge1", "boot_id": "b", "sequence": 1, "sent_at_ms": 1000, "motion_rms": 0.5, "rotation_rad": 0.1}


def extra():
    samples = [SensorSample(i * 0.5, (0, 0, 9.81), (0.1, 0, 0)) for i in range(5)]
    return telemetry_extra(compute_window_features(samples))


class TelemetryV2Tests(unittest.TestCase):
    def test_v1_payload_still_accepted_and_has_no_extra(self):
        t = Telemetry.from_json(json.dumps(V1))
        self.assertIsNone(t.extra)

    def test_v1_serialization_unchanged(self):
        t = Telemetry("edge1", "b", 1, 1000, 0.5, 0.1)
        self.assertEqual(json.loads(t.to_json()), V1)

    def test_v2_round_trip_keeps_old_fields(self):
        t = Telemetry("edge1", "b", 1, 1000, 0.5, 0.1, extra())
        body = json.loads(t.to_json())
        for key, value in V1.items():
            self.assertEqual(body[key], value)
        self.assertEqual(Telemetry.from_json(t.to_json()).extra, extra())

    def test_old_parser_logic_ignores_v2_fields(self):
        body = json.loads(Telemetry("edge1", "b", 1, 1000, 0.5, 0.1, extra()).to_json())
        self.assertLessEqual(set(V1), set(body))

    def test_unknown_schema_treated_as_v1(self):
        self.assertIsNone(Telemetry.from_json(json.dumps({**V1, "schema_version": 99})).extra)

    def test_invalid_v2_field_rejected(self):
        good = json.loads(Telemetry("edge1", "b", 1, 1000, 0.5, 0.1, extra()).to_json())
        for key, bad in (("gyro_rms", -1), ("window_s", "x"), ("acc_dyn_rms", None), ("sensor_fault", 1)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                Telemetry.from_json(json.dumps({**good, key: bad}))

    def test_missing_v1_field_rejected(self):
        for key in V1:
            body = dict(V1)
            del body[key]
            with self.subTest(key=key), self.assertRaises((ValueError, TypeError)):
                Telemetry.from_json(json.dumps(body))

    def test_malformed_values_rejected(self):
        for body in ("[]", "bukan json", json.dumps({**V1, "device_id": "edge9"}),
                     json.dumps({**V1, "motion_rms": -1}), '{"motion_rms": NaN}'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                Telemetry.from_json(body)

    def test_detector_behaves_same_for_v1_and_v2(self):
        def run(with_extra):
            d = WasherDetector(Config(start_s=6, done_s=8, remind_s=20))
            out = []
            for i, rms in enumerate([0.4] * 8 + [0.02] * 8):
                now = 1_790_000_000_000 + i * 2000
                out.append(d.accept(Telemetry("edge1", "b", i, now, rms, 0.0, extra() if with_extra else None), now_ms=now).status)
            return out
        self.assertEqual(run(False), run(True))


if __name__ == "__main__":
    unittest.main()
