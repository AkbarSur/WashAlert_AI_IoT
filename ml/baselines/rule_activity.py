"""Baseline ambang. BUKAN model ML: ambang ditulis manusia, tidak dipelajari.

Memetakan ambang bawaan Config lama ke satu jendela agregat. Keterbatasan: FSM lama memakai
moving average 3 jendela, hysteresis, dan durasi, sedangkan fungsi ini tanpa ingatan. Untuk
perilaku FSM sebenarnya, pakai ml.replay.
"""

WASH_THRESHOLD = 0.25
SPIN_THRESHOLD = 2.0
SPIN_ROTATION = 0.5


def rule_activity(motion_rms_mean: float, rotation_rad_mean: float) -> str:
    if motion_rms_mean >= SPIN_THRESHOLD or rotation_rad_mean >= SPIN_ROTATION:
        return "SPIN"
    return "WASHING" if motion_rms_mean >= WASH_THRESHOLD else "IDLE"
