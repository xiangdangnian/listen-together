import struct
import tempfile
import unittest
import wave
from pathlib import Path

from listen_together.library.cache import LibraryCache
from listen_together.library.models import MediaFile
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

    def test_reimport_replaces_previous_directory_tracks(self) -> None:
        first_dir = self.root / "first"
        second_dir = self.root / "second"
        first_dir.mkdir()
        second_dir.mkdir()
        write_tone(first_dir / "First.wav")
        write_tone(second_dir / "Second.wav")
        first_tracks = self.service.scan_directory(first_dir)
        first_id = self.service.compute_track_id(first_tracks[0].path)

        second_tracks = self.service.scan_directory(second_dir)

        self.assertEqual([track.title for track in second_tracks], ["Second"])
        self.assertEqual([track.title for track in self.service.tracks()], ["Second"])
        self.assertIsNone(self.service.find_by_track_id(first_id))

    def test_sidecar_lrc_is_loaded_and_cleaned(self) -> None:
        track_path = self.root / "Song.wav"
        write_tone(track_path)
        lrc_path = self.root / "Song.lrc"
        lrc_path.write_text(
            "[ar:Artist]\n[00:01.00]第一行歌词\n[00:03.50]第二行歌词\n",
            encoding="utf-8",
        )

        tracks = self.service.scan_directory(self.root)

        self.assertEqual(len(tracks), 1)
        self.assertIn("第一行歌词", tracks[0].lyrics)
        self.assertIn("第二行歌词", tracks[0].lyrics)
        self.assertNotIn("[00:", tracks[0].lyrics)
        self.assertNotIn("[ar:", tracks[0].lyrics)
        self.assertIn("[00:01.00]", tracks[0].lyrics_lrc)

    def test_old_cached_plain_lyrics_are_upgraded_with_timestamps(self) -> None:
        track_path = self.root / "Song.wav"
        write_tone(track_path)
        track_path.with_suffix(".lrc").write_text(
            "[00:01.00]第一行歌词\n",
            encoding="utf-8",
        )
        stat = track_path.stat()
        self.cache.upsert(
            MediaFile(
                path=track_path.resolve(),
                title="Song",
                artist="",
                album="",
                duration_ms=300,
                size_bytes=stat.st_size,
                lyrics="第一行歌词",
            ),
            mtime_ns=stat.st_mtime_ns,
        )

        tracks = self.service.scan_directory(self.root)

        self.assertIn("[00:01.00]", tracks[0].lyrics_lrc)


if __name__ == "__main__":
    unittest.main()
