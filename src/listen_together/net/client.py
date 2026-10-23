import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from listen_together.net.protocol import (
    auth_response,
    receive_file,
    receive_json,
    send_file,
    send_json,
)


class HostClient:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        passphrase: str,
        display_name: str,
        on_message: Callable[[dict[str, Any]], None],
        on_disconnected: Callable[[], None],
        on_reconnected: Callable[[], None] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._passphrase = passphrase
        self._display_name = display_name
        self._on_message = on_message
        self._on_disconnected = on_disconnected
        self._on_reconnected = on_reconnected
        self.member_id: str | None = None
        self.session_token: str | None = None
        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self._reader_thread: threading.Thread | None = None

    @property
    def connected(self) -> bool:
        return self._sock is not None and self.session_token is not None

    def connect(self) -> None:
        self._stop.clear()
        self._connect_once(reconnecting=False)
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="listen-together-client",
            daemon=True,
        )
        self._reader_thread.start()

    def send(self, payload: dict[str, Any]) -> None:
        sock = self._sock
        if sock is None:
            raise ConnectionError("Not connected to the room.")
        with self._send_lock:
            send_json(sock, payload)

    def close(self) -> None:
        self._stop.set()
        sock = self._sock
        self._sock = None
        self.session_token = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def download_track(
        self,
        *,
        track_id: str,
        part_path: Path,
        expected_size: int,
    ) -> None:
        sock = self._open_data_socket("download", track_id)
        try:
            ready = receive_json(sock)
            if ready.get("type") == "error":
                raise RuntimeError(str(ready.get("message", "Download failed.")))
            if ready.get("type") != "ready":
                raise RuntimeError("Invalid download response.")
            if int(ready.get("size_bytes", -1)) != expected_size:
                raise RuntimeError("Downloaded file size does not match track metadata.")
            part_path.parent.mkdir(parents=True, exist_ok=True)
            receive_file(sock, part_path, byte_count=expected_size)
        finally:
            sock.close()

    def upload_track(self, *, track_id: str, path: Path) -> None:
        size_bytes = path.stat().st_size
        sock = self._open_data_socket("upload", track_id)
        try:
            ready = receive_json(sock)
            if ready.get("type") == "error":
                raise RuntimeError(str(ready.get("message", "Upload failed.")))
            if ready.get("type") != "ready":
                raise RuntimeError("Invalid upload response.")
            send_file(sock, path)
            result = receive_json(sock)
            if result.get("type") == "error":
                raise RuntimeError(str(result.get("message", "Upload failed.")))
        finally:
            sock.close()

    def _connect_once(self, *, reconnecting: bool) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=8)
        sock.settimeout(15)
        try:
            send_json(sock, {"kind": "control", "version": 1})
            challenge = receive_json(sock)
            if challenge.get("type") != "challenge":
                raise RuntimeError(str(challenge.get("message", "Invalid room response.")))
            auth_message: dict[str, Any] = {
                "type": "auth",
                "response": auth_response(
                    self._passphrase,
                    str(challenge["nonce"]),
                ),
                "display_name": self._display_name,
            }
            if self.member_id:
                auth_message["member_id"] = self.member_id
            send_json(sock, auth_message)
            welcome = receive_json(sock)
            if welcome.get("type") == "error":
                raise RuntimeError(str(welcome.get("message", "Could not join room.")))
            if welcome.get("type") != "welcome":
                raise RuntimeError("Invalid welcome response.")
        except Exception:
            sock.close()
            raise
        sock.settimeout(None)
        self.member_id = str(welcome["member_id"])
        self.session_token = str(welcome["session_token"])
        self._sock = sock
        if reconnecting and self._on_reconnected is not None:
            self._on_reconnected()

    def _reader_loop(self) -> None:
        backoff_s = 1.0
        while not self._stop.is_set():
            sock = self._sock
            if sock is None:
                break
            try:
                while not self._stop.is_set():
                    message = receive_json(sock)
                    self._on_message(message)
            except (ConnectionError, OSError, ValueError):
                if self._stop.is_set():
                    break
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass
                self._sock = None
                self.session_token = None
                try:
                    self._on_disconnected()
                except Exception:
                    pass

                while not self._stop.is_set():
                    time.sleep(backoff_s)
                    backoff_s = min(5.0, backoff_s + 1.0)
                    try:
                        self._connect_once(reconnecting=True)
                        backoff_s = 1.0
                        break
                    except Exception:
                        continue

    def _open_data_socket(self, action: str, track_id: str) -> socket.socket:
        token = self.session_token
        if token is None:
            raise ConnectionError("Not connected to the room.")
        sock = socket.create_connection((self.host, self.port), timeout=8)
        sock.settimeout(30)
        send_json(
            sock,
            {
                "kind": "data",
                "session_token": token,
                "action": action,
                "track_id": track_id,
            },
        )
        return sock
