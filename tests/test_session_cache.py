import tempfile
import unittest
from pathlib import Path

from listen_together.library.scanner import compute_sha256
from listen_together.transfer.session_cache import CacheFullError, SessionCache


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

    def test_default_cache_budget_is_one_gigabyte(self) -> None:
        cache = SessionCache(self.root / "cache")
        self.addCleanup(cache.clear)

        self.assertEqual(cache.max_bytes, 1024 * 1024 * 1024)

    def test_reservation_evicts_unpinned_cache(self) -> None:
        cache = SessionCache(self.root / "cache", max_bytes=1_000)
        self.addCleanup(cache.clear)
        first = self.root / "first.bin"
        first.write_bytes(b"a" * 600)
        first_id = compute_sha256(first)
        cache.import_file(first, track_id=first_id, expected_hash=first_id)

        second = self.root / "second.bin"
        second.write_bytes(b"b" * 600)
        second_id = compute_sha256(second)
        cache.reserve(second_id, second.stat().st_size)

        self.assertFalse(cache.has_track(first_id))
        self.assertIn(second_id, cache._reservations)
        cache.release_reservation(second_id)

    def test_pinned_track_is_not_evicted(self) -> None:
        cache = SessionCache(self.root / "cache", max_bytes=1_000)
        self.addCleanup(cache.clear)
        first = self.root / "pinned.bin"
        first.write_bytes(b"a" * 600)
        first_id = compute_sha256(first)
        cache.import_file(first, track_id=first_id, expected_hash=first_id)
        cache.set_pinned_track_ids({first_id})

        second = self.root / "large.bin"
        second.write_bytes(b"b" * 600)
        second_id = compute_sha256(second)
        with self.assertRaises(CacheFullError):
            cache.reserve(second_id, second.stat().st_size)
        self.assertTrue(cache.has_track(first_id))

    def test_prune_keeps_three_selected_tracks(self) -> None:
        cache = SessionCache(self.root / "cache", max_bytes=1024 * 1024)
        track_ids = []
        for index in range(4):
            source = self.root / f"track-{index}.bin"
            source.write_bytes(f"track-{index}".encode() * 32)
            track_id = compute_sha256(source)
            track_ids.append(track_id)
            cache.import_file(
                source,
                track_id=track_id,
                expected_hash=track_id,
            )

        cache.prune(keep_track_ids=set(track_ids[1:]))

        self.assertFalse(cache.has_track(track_ids[0]))
        self.assertTrue(all(cache.has_track(track_id) for track_id in track_ids[1:]))


if __name__ == "__main__":
    unittest.main()
