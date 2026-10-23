import unittest
from pathlib import Path

from listen_together.player.base import PlaybackState
from listen_together.player.controller import PlaybackController


class FakePlayerBackend:
    def __init__(self) -> None:
        self.opened_path: Path | None = None
        self.playing = False
        self.position = 0

    def open(self, path: Path) -> int:
        self.opened_path = path
        self.position = 0
        return 120_000

    def play(self) -> None:
        self.playing = True

    def pause(self) -> None:
        self.playing = False

    def seek_ms(self, position_ms: int) -> None:
        self.position = position_ms

    def position_ms(self) -> int:
        return self.position

    def is_playing(self) -> bool:
        return self.playing

    def set_rate(self, rate: float) -> None:
        self.rate = rate

    def set_volume(self, volume: int) -> None:
        self.volume = volume

    def stop(self) -> None:
        self.playing = False
        self.position = 0

    def close(self) -> None:
        self.stop()


class PlaybackControllerTests(unittest.TestCase):
    def test_play_and_pause_update_public_state(self) -> None:
        backend = FakePlayerBackend()
        controller = PlaybackController(backend)

        controller.load(Path("song.mp3"))
        self.assertEqual(controller.state, PlaybackState.READY)

        controller.play()
        self.assertEqual(controller.state, PlaybackState.PLAYING)

        controller.pause()
        self.assertEqual(controller.state, PlaybackState.PAUSED)

    def test_seek_is_clamped_to_loaded_duration(self) -> None:
        backend = FakePlayerBackend()
        controller = PlaybackController(backend)
        controller.load(Path("song.mp3"))

        self.assertEqual(controller.seek_ms(-500), 0)
        self.assertEqual(controller.seek_ms(999_000), 120_000)
        self.assertEqual(backend.position, 120_000)


if __name__ == "__main__":
    unittest.main()
