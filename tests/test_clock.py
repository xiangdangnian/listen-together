import unittest

from listen_together.sync.clock import ClockSynchronizer


class ClockSynchronizerTests(unittest.TestCase):
    def test_estimate_prefers_low_rtt_sample(self) -> None:
        synchronizer = ClockSynchronizer()
        synchronizer.add_sample(
            t0_us=1_000_000,
            t1_us=6_010_000,
            t2_us=6_010_000,
            t3_us=1_020_000,
        )
        synchronizer.add_sample(
            t0_us=2_000_000,
            t1_us=7_100_000,
            t2_us=7_200_000,
            t3_us=2_200_000,
        )

        estimate = synchronizer.estimate()

        self.assertEqual(estimate.rtt_us, 20_000)
        self.assertEqual(estimate.offset_us, 5_000_000)
        self.assertEqual(synchronizer.host_now_us(1_100_000), 6_100_000)


if __name__ == "__main__":
    unittest.main()
