import unittest

from listen_together.sync.drift import DriftCorrector


class DriftCorrectorTests(unittest.TestCase):
    def test_normal_vlc_position_jitter_does_not_trigger_seek(self) -> None:
        corrector = DriftCorrector(
            threshold_ms=500,
            required_hits=5,
            cooldown_s=3.0,
        )

        decisions = [
            corrector.update(drift_ms, now_s=10.0 + index * 0.1)
            for index, drift_ms in enumerate([-157, -47, -150, -80, -160])
        ]

        self.assertFalse(any(decisions))

    def test_persistent_large_drift_seeks_once_then_cools_down(self) -> None:
        corrector = DriftCorrector(
            threshold_ms=500,
            required_hits=5,
            cooldown_s=3.0,
        )
        decisions = [
            corrector.update(-700, now_s=20.0 + index * 0.1)
            for index in range(5)
        ]
        self.assertTrue(decisions[-1])
        self.assertFalse(corrector.update(-700, now_s=20.6))

    def test_reset_clears_accumulated_drift(self) -> None:
        corrector = DriftCorrector(
            threshold_ms=500,
            required_hits=5,
            cooldown_s=3.0,
        )
        for index in range(4):
            self.assertFalse(corrector.update(-700, now_s=30.0 + index * 0.1))

        corrector.reset()

        self.assertFalse(corrector.update(-700, now_s=31.0))


if __name__ == "__main__":
    unittest.main()
