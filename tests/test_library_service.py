import struct
import tempfile
import unittest
import wave
from pathlib import Path

from listen_together.library.cache import LibraryCache
from listen_together.library.service import LibraryService


def write_tone(path: Path, *, duration_ms: int = 300) -> None:
    sample_rate = 8_000
    frame_count = sample_rate * duration_ms // 1_000
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(struct.pack("<h", 0) * frame_count)


class LibraryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.cache = LibraryCache(self.root / "library.sqlite3")
        self.service = LibraryService(self.cache)

    def tearDown(self) -> None:
        self.service.close()
        self.temp_dir.cleanup()

    def test_scan_reads_audio_metadata_and_hash(self) -> None:
        track_path = self.root / "Artist - Song.wav"
        write_tone(track_path, duration_ms=300)

        tracks = self.service.scan_directory(self.root)

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].path, track_path.resolve())
        self.assertEqual(tracks[0].title, "Artist - Song")
        self.assertGreaterEqual(tracks[0].duration_ms, 250)
        track_id = self.service.compute_track_id(track_path)
        self.assertRegex(track_id, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(self.service.find_by_track_id(track_id), track_path.resolve())


if __name__ == "__main__":
    unittest.main()
