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


class AppControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.music_dir = self.root / "music"
        self.music_dir.mkdir()
        write_tone(self.music_dir / "Host Song.wav")

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


if __name__ == "__main__":
    unittest.main()
