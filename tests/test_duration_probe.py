import struct
import tempfile
import unittest
import wave
from pathlib import Path

from listen_together.library.cache import LibraryCache
from listen_together.library.models import MediaFile
from listen_together.library.service import LibraryService
from listen_together.player.vlc_backend import probe_media_duration


def write_tone(path: Path, *, duration_ms: int) -> None:
    sample_rate = 8_000
    frame_count = sample_rate * duration_ms // 1_000
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(struct.pack("<h", 0) * frame_count)


class DurationProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def test_vlc_duration_probe_reads_generated_audio(self) -> None:
        path = self.root / "tone.wav"
        write_tone(path, duration_ms=700)

        self.assertGreaterEqual(probe_media_duration(path), 600)

    def test_invalid_cached_duration_is_revalidated(self) -> None:
        path = self.root / "tone.wav"
        write_tone(path, duration_ms=700)
        cache = LibraryCache(self.root / "library.sqlite3")
        stat = path.stat()
        cache.upsert(
            MediaFile(
                path=path.resolve(),
                title="tone",
                artist="",
                album="",
                duration_ms=1,
                size_bytes=stat.st_size,
            ),
            mtime_ns=stat.st_mtime_ns,
        )
        service = LibraryService(cache)
        self.addCleanup(service.close)

        tracks = service.scan_directory(self.root)

        self.assertEqual(len(tracks), 1)
        self.assertGreaterEqual(tracks[0].duration_ms, 600)


if __name__ == "__main__":
    unittest.main()
