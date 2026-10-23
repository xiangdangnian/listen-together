import hmac
import secrets
import socket
import threading
import time
import uuid
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
from listen_together.transfer.session_cache import SessionCache


ConnectedCallback = Callable[
    [str | None, str, bool],
    str | tuple[str, dict[str, Any] | None],
]
MessageCallback = Callable[[str, dict[str, Any]], None]
MediaCallback = Callable[[str, str, Path], None]


class _Peer:
    def __init__(self, member_id: str, sock: socket.socket) -> None:
        self.member_id = member_id
        self.sock = sock
        self.send_lock = threading.Lock()

    def send(self, payload: dict[str, Any]) -> None:
        with self.send_lock:
            send_json(self.sock, payload)

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class HostServer:
    def __init__(
        self,
        *,
        passphrase: str,
        room_id: str,
        cache: SessionCache,
        on_connected: ConnectedCallback,
        on_disconnected: Callable[[str], None],
        on_message: MessageCallback,
        on_media_received: MediaCallback,
        resolve_media: Callable[[str], Path | None],
        host: str = "0.0.0.0",
        port: int = 0,
        max_peers: int = 7,
    ) -> None:
        self._passphrase = passphrase
        self._room_id = room_id
        self._cache = cache
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._on_message = on_message
        self._on_media_received = on_media_received
        self._resolve_media = resolve_media
        self._host = host
        self._requested_port = port
        self._max_peers = max_peers
        self._listener: socket.socket | None = None
        self._running = threading.Event()
        self._lock = threading.RLock()
        self._peers: dict[str, _Peer] = {}
        self._tokens: dict[str, str] = {}
        self._expected_uploads: dict[tuple[str, str], int] = {}
        self._threads: list[threading.Thread] = []
        self._accept_thread: threading.Thread | None = None

    def start(self) -> int:
        if self._listener is not None:
            return self._listener.getsockname()[1]
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self._host, self._requested_port))
        listener.listen(16)
        listener.settimeout(0.5)
        self._listener = listener
        self._running.set()
        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name="listen-together-server",
            daemon=True,
        )
        self._accept_thread.start()
        return listener.getsockname()[1]

    def stop(self) -> None:
        self._running.clear()
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
            self._listener = None
        with self._lock:
            peers = list(self._peers.values())
            self._peers.clear()
            self._tokens.clear()
        for peer in peers:
            peer.close()

    def send_to(self, member_id: str, payload: dict[str, Any]) -> bool:
        with self._lock:
            peer = self._peers.get(member_id)
        if peer is None:
            return False
        try:
            peer.send(payload)
            return True
        except OSError:
            self._remove_peer(member_id)
            return False

    def broadcast(self, payload: dict[str, Any], *, exclude: str | None = None) -> None:
        with self._lock:
            peers = list(self._peers.items())
        for member_id, peer in peers:
            if member_id == exclude:
                continue
            try:
                peer.send(payload)
            except OSError:
                self._remove_peer(member_id)

    def expect_upload(self, member_id: str, track_id: str, size_bytes: int) -> None:
        with self._lock:
            self._expected_uploads[(member_id, track_id)] = size_bytes

    def cancel_uploads(self, member_id: str) -> None:
        with self._lock:
            stale = [
                key for key in self._expected_uploads if key[0] == member_id
            ]
            for key in stale:
                self._expected_uploads.pop(key, None)

    def disconnect_member(self, member_id: str) -> None:
        if self._remove_peer(member_id):
            self._on_disconnected(member_id)

    def _accept_loop(self) -> None:
        while self._running.is_set() and self._listener is not None:
            try:
                client_sock, _address = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            thread = threading.Thread(
                target=self._handle_connection,
                args=(client_sock,),
                name="listen-together-peer",
                daemon=True,
            )
            with self._lock:
                self._threads.append(thread)
            thread.start()

    def _handle_connection(self, client_sock: socket.socket) -> None:
        member_id: str | None = None
        try:
            client_sock.settimeout(30)
            first = receive_json(client_sock)
            kind = first.get("kind")
            if kind == "data":
                self._handle_data_connection(client_sock, first)
                return
            if kind != "control":
                send_json(client_sock, {"type": "error", "message": "Unknown connection type."})
                return

            nonce = secrets.token_urlsafe(24)
            send_json(
                client_sock,
                {
                    "type": "challenge",
                    "nonce": nonce,
                    "room_id": self._room_id,
                },
            )
            auth = receive_json(client_sock)
            if auth.get("type") != "auth" or not hmac.compare_digest(
                str(auth.get("response", "")),
                auth_response(self._passphrase, nonce),
            ):
                send_json(client_sock, {"type": "error", "message": "房间口令错误。"})
                return

            requested_member_id = auth.get("member_id")
            if requested_member_id is not None:
                requested_member_id = str(requested_member_id)
            with self._lock:
                if (
                    len(self._peers) >= self._max_peers
                    and requested_member_id not in self._peers
                ):
                    send_json(
                        client_sock,
                        {"type": "error", "message": "房间人数已满。"},
                    )
                    return
            display_name = str(auth.get("display_name") or "未命名成员")[:40]
            connected_result = self._on_connected(
                requested_member_id,
                display_name,
                requested_member_id is not None,
            )
            initial_message: dict[str, Any] | None = None
            if isinstance(connected_result, tuple):
                member_id, initial_message = connected_result
            else:
                member_id = connected_result

            token = uuid.uuid4().hex
            with self._lock:
                self._peers[member_id] = _Peer(member_id, client_sock)
                self._tokens[token] = member_id
            send_json(
                client_sock,
                {
                    "type": "welcome",
                    "member_id": member_id,
                    "session_token": token,
                    "host_monotonic_us": time.monotonic_ns() // 1_000,
                },
            )
            if initial_message is not None:
                self.send_to(member_id, initial_message)

            client_sock.settimeout(None)
            while self._running.is_set():
                message = receive_json(client_sock)
                self._on_message(member_id, message)
        except (ConnectionError, OSError, ValueError):
            pass
        finally:
            if member_id is not None:
                removed = self._remove_peer(member_id, expected_sock=client_sock)
                if removed:
                    try:
                        self._on_disconnected(member_id)
                    except Exception:
                        pass
            try:
                client_sock.close()
            except OSError:
                pass

    def _handle_data_connection(
        self,
        client_sock: socket.socket,
        hello: dict[str, Any],
    ) -> None:
        token = str(hello.get("session_token", ""))
        with self._lock:
            member_id = self._tokens.get(token)
        if member_id is None:
            send_json(client_sock, {"type": "error", "message": "会话已失效。"})
            return

        action = hello.get("action")
        track_id = str(hello.get("track_id", ""))
        if action == "download":
            source = self._resolve_media(track_id)
            if source is None or not source.is_file():
                send_json(client_sock, {"type": "error", "message": "Host 尚未准备好该歌曲。"})
                return
            size_bytes = source.stat().st_size
            send_json(
                client_sock,
                {"type": "ready", "size_bytes": size_bytes, "track_id": track_id},
            )
            send_file(client_sock, source)
            return

        if action == "upload":
            with self._lock:
                expected_size = self._expected_uploads.pop((member_id, track_id), None)
            if expected_size is None:
                send_json(client_sock, {"type": "error", "message": "未请求该文件。"})
                return
            try:
                self._cache.ensure_capacity(expected_size)
            except Exception as error:
                send_json(client_sock, {"type": "error", "message": str(error)})
                return
            send_json(
                client_sock,
                {"type": "ready", "size_bytes": expected_size, "track_id": track_id},
            )
            part = self._cache.part_path(track_id)
            try:
                receive_file(client_sock, part, byte_count=expected_size)
                stored = self._cache.finalize_part(
                    part,
                    track_id=track_id,
                    expected_hash=track_id,
                    expected_size=expected_size,
                )
                self._on_media_received(member_id, track_id, stored)
                send_json(client_sock, {"type": "transfer_complete", "track_id": track_id})
            except Exception as error:
                part.unlink(missing_ok=True)
                send_json(client_sock, {"type": "error", "message": str(error)})
            return

        send_json(client_sock, {"type": "error", "message": "未知传输类型。"})

    def _remove_peer(
        self,
        member_id: str,
        *,
        expected_sock: socket.socket | None = None,
    ) -> bool:
        with self._lock:
            peer = self._peers.get(member_id)
            if expected_sock is not None and (
                peer is None or peer.sock is not expected_sock
            ):
                return False
            peer = self._peers.pop(member_id, None)
            stale_tokens = [
                token for token, owner in self._tokens.items() if owner == member_id
            ]
            for token in stale_tokens:
                self._tokens.pop(token, None)
        if peer is not None:
            peer.close()
        return True

