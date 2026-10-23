import tempfile
import unittest
from pathlib import Path

from listen_together.library.scanner import compute_sha256
from listen_together.transfer.session_cache import SessionCache


class SessionCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "source.wav"
        self.source.write_bytes(b"0123456789" * 128)
        self.track_id = compute_sha256(self.source)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_import_prune_and_clear(self) -> None:
        cache = SessionCache(self.root / "cache", max_bytes=1024 * 1024)
        stored = cache.import_file(
            self.source,
            track_id=self.track_id,
            expected_hash=self.track_id,
        )

        self.assertTrue(stored.is_file())
        self.assertTrue(cache.has_track(self.track_id))

        cache.prune(keep_track_ids=set())
        self.assertFalse(stored.exists())

        cache.import_file(
            self.source,
            track_id=self.track_id,
            expected_hash=self.track_id,
        )
        session_dir = cache.session_dir
        cache.clear()
        self.assertFalse(session_dir.exists())

    def test_stale_sessions_are_removed_on_start(self) -> None:
        cache_root = self.root / "cache"
        stale = cache_root / "session-stale"
        stale.mkdir(parents=True)
        (stale / "old.media").write_bytes(b"old")

        cache = SessionCache(cache_root, max_bytes=1024 * 1024)

        self.assertFalse(stale.exists())
        self.assertTrue(cache.session_dir.exists())
        cache.clear()


if __name__ == "__main__":
    unittest.main()
