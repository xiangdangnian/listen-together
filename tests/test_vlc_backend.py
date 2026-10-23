import math
import struct
import tempfile
import time
import unittest
import wave
from pathlib import Path

from listen_together.player.vlc_backend import VLCBackend


def wait_until(predicate, *, timeout_s: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class VLCBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp_dir = tempfile.TemporaryDirectory()
        cls.audio_path = Path(cls._temp_dir.name) / "tone.wav"
        sample_rate = 44_100
        duration_s = 2
        with wave.open(str(cls.audio_path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            frames = bytearray()
            for index in range(sample_rate * duration_s):
                value = int(8_000 * math.sin(2 * math.pi * 440 * index / sample_rate))
                frames.extend(struct.pack("<h", value))
            audio.writeframes(bytes(frames))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp_dir.cleanup()

    def test_open_play_pause_and_seek(self) -> None:
        backend = VLCBackend(audio_output="dummy")
        self.addCleanup(backend.close)

        duration_ms = backend.open(self.audio_path)
        self.assertGreaterEqual(duration_ms, 1_900)
        backend.set_rate(1.02)
        backend.set_rate(1.0)

        backend.play()
        self.assertTrue(wait_until(lambda: backend.position_ms() >= 100))

        backend.pause()
        self.assertTrue(wait_until(lambda: not backend.is_playing()))

        backend.seek_ms(1_000)
        self.assertTrue(wait_until(lambda: backend.position_ms() >= 950))


if __name__ == "__main__":
    unittest.main()
