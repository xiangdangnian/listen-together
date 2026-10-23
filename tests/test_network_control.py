import tempfile
import threading
import time
import unittest
from pathlib import Path

from listen_together.library.scanner import compute_sha256
from listen_together.net.client import HostClient
from listen_together.net.server import HostServer
from listen_together.transfer.session_cache import SessionCache


def wait_event(event: threading.Event, timeout_s: float = 5.0) -> bool:
    return event.wait(timeout_s)


class NetworkControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache = SessionCache(Path(self.temp_dir.name) / "cache")
        self.received = []
        self.message_event = threading.Event()
        self.connected_event = threading.Event()
        self.upload_event = threading.Event()
        self.reconnected_event = threading.Event()
        self.uploaded_path: Path | None = None
        self.download_source: Path | None = None
        self.server = HostServer(
            passphrase="123456",
            room_id="room-test",
            cache=self.cache,
            on_connected=self._on_connected,
            on_disconnected=lambda _member_id: None,
            on_message=self._on_message,
            on_media_received=self._on_media_received,
            resolve_media=lambda _track_id: self.download_source,
        )
        self.port = self.server.start()
        self.client = HostClient(
            host="127.0.0.1",
            port=self.port,
            passphrase="123456",
            display_name="Guest",
            on_message=self._on_client_message,
            on_disconnected=lambda: None,
            on_reconnected=self.reconnected_event.set,
        )

    def tearDown(self) -> None:
        self.client.close()
        self.server.stop()
        self.cache.clear()
        self.temp_dir.cleanup()

    def _on_connected(self, member_id: str, _display_name: str, _reconnected: bool) -> str:
        self.connected_event.set()
        return member_id or "member-guest"

    def _on_message(self, _member_id: str, message: dict) -> None:
        self.received.append(message)
        self.message_event.set()

    def _on_client_message(self, message: dict) -> None:
        self.received.append(message)
        self.message_event.set()

    def _on_media_received(self, _member_id: str, _track_id: str, path: Path) -> None:
        self.uploaded_path = path
        self.upload_event.set()

    def test_control_handshake_and_bidirectional_messages(self) -> None:
        self.client.connect()
        self.assertTrue(wait_event(self.connected_event))

        self.client.send({"type": "hello_from_client"})
        self.assertTrue(wait_event(self.message_event))
        self.assertIn(
            {"type": "hello_from_client"},
            [message for message in self.received if message.get("type") == "hello_from_client"],
        )

        self.message_event.clear()
        self.server.broadcast({"type": "snapshot", "value": 1})
        self.assertTrue(wait_event(self.message_event))
        self.assertIn(
            {"type": "snapshot", "value": 1},
            [message for message in self.received if message.get("type") == "snapshot"],
        )

    def test_wrong_room_passphrase_is_rejected(self) -> None:
        bad_client = HostClient(
            host="127.0.0.1",
            port=self.port,
            passphrase="wrong",
            display_name="Guest",
            on_message=lambda _message: None,
            on_disconnected=lambda: None,
        )
        with self.assertRaises(RuntimeError):
            bad_client.connect()
        bad_client.close()

    def test_file_can_be_downloaded_and_uploaded(self) -> None:
        self.client.connect()
        self.assertTrue(wait_event(self.connected_event))
        source = Path(self.temp_dir.name) / "transfer-source.wav"
        source.write_bytes(bytes(range(256)) * 16)
        track_id = compute_sha256(source)
        self.download_source = source

        download_part = Path(self.temp_dir.name) / "download.part"
        self.client.download_track(
            track_id=track_id,
            part_path=download_part,
            expected_size=source.stat().st_size,
        )
        self.assertEqual(download_part.read_bytes(), source.read_bytes())

        self.server.expect_upload(
            self.client.member_id or "",
            track_id,
            source.stat().st_size,
        )
        self.client.upload_track(track_id=track_id, path=source)
        self.assertTrue(wait_event(self.upload_event))
        self.assertIsNotNone(self.uploaded_path)
        self.assertEqual(self.uploaded_path.read_bytes(), source.read_bytes())

    def test_client_reconnects_after_connection_drop(self) -> None:
        self.client.connect()
        self.assertTrue(wait_event(self.connected_event))
        member_id = self.client.member_id or ""

        self.server.disconnect_member(member_id)

        self.assertTrue(wait_event(self.reconnected_event, timeout_s=8.0))
        self.assertTrue(self.client.connected)
        self.assertEqual(self.client.member_id, member_id)


if __name__ == "__main__":
    unittest.main()
