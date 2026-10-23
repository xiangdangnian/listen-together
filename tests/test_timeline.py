import unittest

from listen_together.sync.timeline import PlaybackAnchor, Timeline


class TimelineTests(unittest.TestCase):
    def test_playing_position_advances_with_host_clock(self) -> None:
        timeline = Timeline()
        anchor = PlaybackAnchor(
            epoch=3,
            track_id="track-a",
            duration_ms=180_000,
            playing=True,
            anchor_position_ms=42_000,
            anchor_host_us=1_000_000,
            rate=1.0,
        )

        self.assertEqual(
            timeline.target_position_ms(anchor, host_now_us=2_500_000),
            43_500,
        )

    def test_stale_playback_epoch_is_rejected(self) -> None:
        timeline = Timeline()

        self.assertFalse(timeline.accepts_epoch(current_epoch=5, incoming_epoch=4))
        self.assertTrue(timeline.accepts_epoch(current_epoch=5, incoming_epoch=5))

    def test_paused_position_is_fixed_and_playback_end_is_clamped(self) -> None:
        timeline = Timeline()
        paused = PlaybackAnchor(
            epoch=4,
            track_id="track-b",
            duration_ms=60_000,
            playing=False,
            anchor_position_ms=15_000,
            anchor_host_us=10_000_000,
        )
        playing = PlaybackAnchor(
            epoch=5,
            track_id="track-c",
            duration_ms=60_000,
            playing=True,
            anchor_position_ms=59_500,
            anchor_host_us=20_000_000,
        )

        self.assertEqual(
            timeline.target_position_ms(paused, host_now_us=30_000_000),
            15_000,
        )
        self.assertEqual(
            timeline.target_position_ms(playing, host_now_us=21_000_000),
            60_000,
        )


if __name__ == "__main__":
    unittest.main()
