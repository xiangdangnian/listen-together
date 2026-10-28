import struct
import tempfile
import time
import unittest
import wave
from pathlib import Path

from listen_together.app_controller import AppController
from tests.fakes import FakePlayerBackend


def write_tone(path: Path, *, duration_ms: int = 500) -> None:
    sample_rate = 8_000
    frame_count = sample_rate * duration_ms // 1_000
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(struct.pack("<h", 0) * frame_count)


def wait_for(predicate, *, timeout_s: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.03)
    return False


class ReloadTrackingBackend(FakePlayerBackend):
    def __init__(self) -> None:
        super().__init__()
        self.opened_paths: list[Path] = []

    def open(self, path: Path) -> int:
        self.opened_paths.append(Path(path))
        return super().open(path)

class AppControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.music_dir = self.root / "music"
        self.music_dir.mkdir()
        write_tone(self.music_dir / "Host Song.wav", duration_ms=5_000)

    def test_local_track_becomes_ready_and_starts(self) -> None:
        controller = AppController(
            data_dir=self.root / "host-data",
            backend_factory=FakePlayerBackend,
        )
        self.addCleanup(controller.close)
        tracks = controller.library.scan_directory(self.music_dir)
        controller.add_track(tracks[0])

        def queue_has_track() -> bool:
            controller.tick()
            return len(controller.snapshot.get("queue", [])) == 1

        self.assertTrue(wait_for(queue_has_track))
        self.assertTrue(
            wait_for(
                lambda: (
                    controller.tick()
                    or controller.snapshot.get("playback", {}).get("playing", False)
                )
            )
        )

    def test_client_downloads_host_track_and_syncs(self) -> None:
        host = AppController(
            data_dir=self.root / "host-data",
            backend_factory=FakePlayerBackend,
        )
        client = AppController(
            data_dir=self.root / "client-data",
            backend_factory=FakePlayerBackend,
        )
        self.addCleanup(client.close)
        self.addCleanup(host.close)

        room_info = host.create_room(
            room_name="Test Room",
            display_name="Host",
            password="123456",
            port=0,
        )
        client.join_room(
            host="127.0.0.1",
            port=room_info["port"],
            password="123456",
            display_name="Guest",
        )
        tracks = host.library.scan_directory(self.music_dir)
        host.add_track(tracks[0])

        def both_are_synced() -> bool:
            host.tick()
            client.tick()
            playback = client.snapshot.get("playback", {})
            return bool(playback.get("playing"))

        self.assertTrue(wait_for(both_are_synced, timeout_s=12.0))
        client_path = client.current_media_path()
        self.assertIsNotNone(client_path)
        self.assertTrue(client_path.is_file())
        session_dir = client.cache.session_dir
        client.leave_room()
        self.assertFalse(session_dir.exists())

    def test_client_can_be_the_only_source_for_a_track(self) -> None:
        host_music = self.root / "host-music"
        client_music = self.root / "client-music"
        host_music.mkdir()
        client_music.mkdir()
        write_tone(client_music / "Client Song.wav")
        host = AppController(
            data_dir=self.root / "host-data",
            backend_factory=FakePlayerBackend,
        )
        client = AppController(
            data_dir=self.root / "client-data",
            backend_factory=FakePlayerBackend,
        )
        self.addCleanup(client.close)
        self.addCleanup(host.close)

        room_info = host.create_room(
            room_name="Source Test",
            display_name="Host",
            password="123456",
            port=0,
        )
        client.join_room(
            host="127.0.0.1",
            port=room_info["port"],
            password="123456",
            display_name="Guest",
        )
        client_tracks = client.library.scan_directory(client_music)
        client.add_track(client_tracks[0])

        def playback_started() -> bool:
            host.tick()
            client.tick()
            return bool(host.snapshot.get("playback", {}).get("playing"))

        self.assertTrue(wait_for(playback_started, timeout_s=12.0))
        host_path = host.current_media_path()
        self.assertIsNotNone(host_path)
        self.assertTrue(host_path.is_file())

    def test_next_track_is_downloaded_as_a_complete_file(self) -> None:
        write_tone(self.music_dir / "Next Song.wav", duration_ms=6_000)
        host = AppController(
            data_dir=self.root / "host-data",
            backend_factory=FakePlayerBackend,
        )
        client = AppController(
            data_dir=self.root / "client-data",
            backend_factory=FakePlayerBackend,
        )
        self.addCleanup(client.close)
        self.addCleanup(host.close)

        room_info = host.create_room(
            room_name="Prefetch Test",
            display_name="Host",
            password="123456",
            port=0,
        )
        client.join_room(
            host="127.0.0.1",
            port=room_info["port"],
            password="123456",
            display_name="Guest",
        )
        tracks = host.library.scan_directory(self.music_dir)
        for track in tracks:
            host.add_track(track)

        def queue_ready() -> bool:
            host.tick()
            client.tick()
            return len(host.snapshot.get("queue", [])) == 2

        self.assertTrue(wait_for(queue_ready))
        next_path = next(
            track.path for track in tracks if track.path.name == "Next Song.wav"
        )
        next_track_id = host.library.compute_track_id(next_path)

        def next_file_cached() -> bool:
            host.tick()
            client.tick()
            return bool(client.cache and client.cache.has_track(next_track_id))

        self.assertTrue(wait_for(next_file_cached, timeout_s=12.0))
        cached = client.cache.track_path(next_track_id)
        self.assertEqual(cached.stat().st_size, next_path.stat().st_size)

    def test_batch_add_imports_every_track_in_current_library(self) -> None:
        write_tone(self.music_dir / "Second Song.wav", duration_ms=6_000)
        controller = AppController(
            data_dir=self.root / "data",
            backend_factory=FakePlayerBackend,
        )
        self.addCleanup(controller.close)
        tracks = controller.library.scan_directory(self.music_dir)
        controller.add_tracks(tracks)

        def all_added() -> bool:
            controller.tick()
            return len(controller.snapshot.get("queue", [])) == len(tracks)

        self.assertTrue(wait_for(all_added))

    def test_removing_current_track_stops_old_player(self) -> None:
        controller = AppController(
            data_dir=self.root / "data",
            backend_factory=FakePlayerBackend,
        )
        self.addCleanup(controller.close)
        tracks = controller.library.scan_directory(self.music_dir)
        controller.add_track(tracks[0])

        def playing() -> bool:
            controller.tick()
            return bool(
                controller.player
                and controller.player.state.value == "playing"
            )

        self.assertTrue(wait_for(playing))
        queue_id = controller.snapshot["queue"][0]["queue_id"]
        controller.remove_queue_item(queue_id)
        controller.tick()

        self.assertIsNotNone(controller.player)
        self.assertNotEqual(controller.player.state.value, "playing")


    def test_client_batch_add_and_remove_use_single_queue_updates(self) -> None:
        client_music = self.root / "client-music"
        client_music.mkdir()
        for index in range(3):
            write_tone(client_music / f"Client {index}.wav", duration_ms=3_000 + index * 1_000)
        host = AppController(
            data_dir=self.root / "host-data",
            backend_factory=FakePlayerBackend,
        )
        client = AppController(
            data_dir=self.root / "client-data",
            backend_factory=FakePlayerBackend,
        )
        self.addCleanup(client.close)
        self.addCleanup(host.close)
        room_info = host.create_room(
            room_name="Batch Test",
            display_name="Host",
            password="123456",
            port=0,
        )
        client.join_room(
            host="127.0.0.1",
            port=room_info["port"],
            password="123456",
            display_name="Guest",
        )
        tracks = client.library.scan_directory(client_music)
        client.add_tracks(tracks)

        def all_added() -> bool:
            host.tick()
            client.tick()
            return len(host.snapshot.get("queue", [])) == 3

        self.assertTrue(wait_for(all_added, timeout_s=12.0))
        queue_ids = [
            item["queue_id"] for item in host.snapshot["queue"][:2]
        ]
        client.remove_queue_items(queue_ids)

        def all_removed() -> bool:
            host.tick()
            client.tick()
            return len(host.snapshot.get("queue", [])) == 1

        self.assertTrue(wait_for(all_removed, timeout_s=12.0))
    def test_single_track_loop_reloads_backend(self) -> None:
        loop_music = self.root / "loop-music"
        loop_music.mkdir()
        loop_path = loop_music / "Loop.wav"
        write_tone(loop_path, duration_ms=400)
        backend = ReloadTrackingBackend()
        controller = AppController(
            data_dir=self.root / "loop-data",
            backend_factory=lambda: backend,
        )
        self.addCleanup(controller.close)
        tracks = controller.library.scan_directory(loop_music)
        controller.room.set_playback_mode("loop")
        controller.add_track(tracks[0])
        first_run: int | None = None

        def looped_again() -> bool:
            nonlocal first_run
            controller.tick()
            playback = controller.snapshot.get("playback", {})
            if playback.get("playing") and first_run is None:
                first_run = int(playback.get("run_id", 0))
            return bool(
                first_run is not None
                and int(playback.get("run_id", 0)) > first_run
                and len(backend.opened_paths) >= 2
            )

        self.assertTrue(wait_for(looped_again, timeout_s=5.0))
        self.assertEqual(backend.opened_paths[0], loop_path.resolve())
        self.assertEqual(backend.opened_paths[1], loop_path.resolve())

    def test_multi_track_loop_reloads_first_track(self) -> None:
        loop_music = self.root / "multi-loop-music"
        loop_music.mkdir()
        first_path = loop_music / "First.wav"
        second_path = loop_music / "Second.wav"
        write_tone(first_path, duration_ms=300)
        write_tone(second_path, duration_ms=400)
        backend = ReloadTrackingBackend()
        controller = AppController(
            data_dir=self.root / "multi-loop-data",
            backend_factory=lambda: backend,
        )
        self.addCleanup(controller.close)
        tracks = controller.library.scan_directory(loop_music)
        controller.room.set_playback_mode("loop")
        controller.add_tracks(tracks)

        def wrapped_playlist() -> bool:
            controller.tick()
            return len(backend.opened_paths) >= 3

        self.assertTrue(wait_for(wrapped_playlist, timeout_s=5.0))
        self.assertEqual(
            backend.opened_paths[:3],
            [
                first_path.resolve(),
                second_path.resolve(),
                first_path.resolve(),
            ],
        )
    def test_pause_resume_does_not_reload_backend(self) -> None:
        backend = ReloadTrackingBackend()
        controller = AppController(
            data_dir=self.root / "pause-data",
            backend_factory=lambda: backend,
        )
        self.addCleanup(controller.close)
        tracks = controller.library.scan_directory(self.music_dir)
        controller.add_track(tracks[0])

        def playing() -> bool:
            controller.tick()
            return bool(controller.snapshot.get("playback", {}).get("playing"))

        self.assertTrue(wait_for(playing))
        opened_once = len(backend.opened_paths)
        controller.play_pause()
        controller.tick()
        controller.play_pause()
        controller.tick()
        self.assertEqual(len(backend.opened_paths), opened_once)
    def test_duplicate_add_is_rejected_with_message(self) -> None:
        controller = AppController(
            data_dir=self.root / "data",
            backend_factory=FakePlayerBackend,
        )
        self.addCleanup(controller.close)
        events: list[tuple[str, object]] = []
        controller.set_event_callback(lambda kind, payload: events.append((kind, payload)))
        track = controller.library.scan_directory(self.music_dir)[0]
        controller.add_track(track)

        self.assertTrue(wait_for(lambda: (controller.tick() or bool(controller.snapshot.get("queue")))))
        controller.add_track(track)

        self.assertTrue(
            wait_for(
                lambda: (
                    controller.tick()
                    or any(
                        kind == "event" and "已有" in str(payload)
                        for kind, payload in events
                    )
                )
            )
        )
        self.assertEqual(len(controller.snapshot.get("queue", [])), 1)

if __name__ == "__main__":
    unittest.main()
