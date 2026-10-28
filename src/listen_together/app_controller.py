import json
import queue
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from listen_together.domain.room import HostRoom, monotonic_us
from listen_together.library.cache import LibraryCache
from listen_together.library.models import MediaFile
from listen_together.library.service import LibraryService
from listen_together.net.addresses import best_local_ipv4
from listen_together.net.client import HostClient
from listen_together.net.server import HostServer
from listen_together.player.base import PlayerBackend
from listen_together.player.controller import PlaybackController
from listen_together.player.vlc_backend import VLCBackend
from listen_together.sync.clock import ClockSynchronizer
from listen_together.sync.drift import DriftCorrector
from listen_together.sync.timeline import PlaybackAnchor, Timeline
from listen_together.transfer.session_cache import CacheFullError, SessionCache


EventCallback = Callable[[str, Any], None]
BackendFactory = Callable[[], PlayerBackend]
QUEUE_BATCH_SIZE = 50


class AppController:
    def __init__(
        self,
        *,
        data_dir: Path,
        backend_factory: BackendFactory | None = None,
        on_event: EventCallback | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._on_event = on_event
        self._backend_factory = backend_factory or VLCBackend
        self._event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._lock = threading.RLock()
        self.library_cache = LibraryCache(self.data_dir / "library.sqlite3")
        self.library = LibraryService(self.library_cache)
        self.player: PlaybackController | None = None
        self.cache: SessionCache | None = None
        self.room: HostRoom | None = None
        self.server: HostServer | None = None
        self.client: HostClient | None = None
        self.clock: ClockSynchronizer | None = None
        self.role = "local"
        self.member_id = "host"
        self.display_name = "本机"
        self.room_password = ""
        self.port = 43871
        self.host_address = ""
        self.snapshot: dict[str, Any] = {}
        self._snapshot_received_at = time.monotonic()
        self.connection_status = "本地"
        self._timeline = Timeline()
        self._drift_corrector = DriftCorrector()
        self._snapshot_dirty = True
        self._last_snapshot_signature = ""
        self._last_broadcast_at = 0.0
        self._last_ping_at = 0.0
        self._pending_downloads: set[str] = set()
        self._pending_uploads: set[str] = set()
        self._hashing_paths: set[Path] = set()
        self._loaded_track_id: str | None = None
        self._loaded_run_id: int | None = None
        self._pending_host_requests: set[str] = set()
        self._start_local_session(self.display_name)

    @property
    def is_in_room(self) -> bool:
        return self.role in {"host", "client"}

    @property
    def is_host(self) -> bool:
        return self.role in {"local", "host"}

    def set_event_callback(self, callback: EventCallback) -> None:
        self._on_event = callback

    def library_tracks(self) -> list[MediaFile]:
        return self.library.tracks()

    def search_library(self, query: str) -> list[MediaFile]:
        return self.library.search(query)

    def scan_library_async(self, directory: Path) -> None:
        def run() -> None:
            try:
                tracks = self.library.scan_directory(directory)
                self._event_queue.put(("library_scanned", tracks))
            except Exception as error:
                self._event_queue.put(("error", f"音乐库扫描失败：{error}"))

        threading.Thread(target=run, name="library-scan", daemon=True).start()

    def start_local_session(self, display_name: str = "本机") -> None:
        self._stop_current_session()
        self._start_local_session(display_name)

    def create_room(
        self,
        *,
        room_name: str,
        display_name: str,
        password: str,
        port: int = 43871,
    ) -> dict[str, Any]:
        self._stop_current_session()
        self.role = "host"
        self.display_name = display_name or "房主"
        self.room_password = password
        self.port = port
        self.member_id = "host"
        self.cache = SessionCache(self.data_dir / "cache")
        self.room = HostRoom(
            room_id=f"room_{uuid.uuid4().hex}",
            room_name=room_name or "一起听歌",
        )
        self.room.add_member(
            self.display_name,
            member_id=self.member_id,
            is_host=True,
        )
        self.server = HostServer(
            passphrase=password,
            room_id=self.room.room_id,
            cache=self.cache,
            on_connected=self._on_host_connected,
            on_disconnected=self._on_host_disconnected,
            on_message=self._on_host_message,
            on_media_received=self._on_host_media_received,
            resolve_media=self._resolve_host_media,
            port=port,
        )
        try:
            actual_port = self.server.start()
        except Exception:
            display_name = self.display_name
            self._stop_current_session()
            self._start_local_session(display_name)
            raise
        self.port = actual_port
        self.host_address = best_local_ipv4()
        self.connection_status = "房间已创建"
        self._snapshot_dirty = True
        self._refresh_snapshot(force=True)
        return {
            "room_name": room_name,
            "address": self.host_address,
            "port": actual_port,
            "password": password,
        }

    def join_room(
        self,
        *,
        host: str,
        port: int,
        password: str,
        display_name: str,
    ) -> None:
        self._stop_current_session()
        self.role = "client"
        self.display_name = display_name or "听众"
        self.room_password = password
        self.port = port
        self.host_address = host
        self.cache = SessionCache(self.data_dir / "cache")
        self.clock = ClockSynchronizer()
        self.client = HostClient(
            host=host,
            port=port,
            passphrase=password,
            display_name=self.display_name,
            on_message=lambda message: self._event_queue.put(
                ("client_message", message)
            ),
            on_disconnected=lambda: self._event_queue.put(
                ("client_disconnected", None)
            ),
            on_reconnected=lambda: self._event_queue.put(
                ("client_reconnected", None)
            ),
        )
        try:
            self.client.connect()
        except Exception:
            display_name = self.display_name
            self._stop_current_session()
            self._start_local_session(display_name)
            raise
        self.member_id = self.client.member_id or ""
        self.connection_status = "已连接"
        self._send_clock_ping()

    def leave_room(self) -> None:
        display_name = self.display_name
        self._stop_current_session()
        self._start_local_session(display_name)

    def close(self) -> None:
        self._stop_current_session()
        if self.player is not None:
            try:
                self.player.close()
            except Exception:
                pass
            self.player = None
        self.library.close()

    def tick(self) -> None:
        self._drain_events()
        self._update_cache_pins()
        if self.role in {"local", "host"}:
            self._ensure_player()
            if self.room is not None:
                self.room.tick()
            self._prepare_host_media(include_prefetch=False)
            self._sync_playback()
            self._refresh_snapshot()
            if self._can_prefetch_full_next():
                self._prepare_host_media(include_prefetch=True)
        else:
            self._prepare_client_media(include_prefetch=False)
            self._sync_playback()
            self._maybe_send_clock_ping()
            if self._can_prefetch_full_next():
                self._prepare_client_media(include_prefetch=True)
        self._prune_cache()
        self._drain_events()

    def add_track(self, media: MediaFile) -> None:
        self.add_tracks([media])

    def add_tracks(self, media_files: list[MediaFile]) -> None:
        pending: list[MediaFile] = []
        with self._lock:
            for media in media_files:
                path = media.path.resolve()
                if path in self._hashing_paths:
                    continue
                self._hashing_paths.add(path)
                pending.append(media)
        if not pending:
            return

        def run() -> None:
            batch: list[tuple[MediaFile, str]] = []
            for media in pending:
                path = media.path.resolve()
                try:
                    track_id = self.library.compute_track_id(path)
                    batch.append((media, track_id))
                    if len(batch) >= QUEUE_BATCH_SIZE:
                        self._event_queue.put(("tracks_hashed", list(batch)))
                        batch.clear()
                except Exception as error:
                    self._event_queue.put(("error", f"计算文件指纹失败：{error}"))
                finally:
                    with self._lock:
                        self._hashing_paths.discard(path)
            if batch:
                self._event_queue.put(("tracks_hashed", batch))

        threading.Thread(target=run, name="track-hash-batch", daemon=True).start()

    def play_pause(self) -> None:
        if self.role in {"local", "host"}:
            if self.room is None:
                return
            if self.room.snapshot()["playback"]["playing"]:
                self.room.pause()
            else:
                self.room.play()
            self._snapshot_dirty = True
            self._refresh_snapshot(force=True)
        elif self.role == "client" and self.client is not None:
            self._client_send({"type": "play_pause"})
        self._drift_corrector.reset()

    def seek(self, position_ms: int) -> None:
        if self.role in {"local", "host"}:
            if self.room is not None:
                self.room.seek(position_ms)
                self._snapshot_dirty = True
                self._refresh_snapshot(force=True)
        elif self.role == "client" and self.client is not None:
            self._client_send({"type": "seek", "position_ms": int(position_ms)})
        self._drift_corrector.reset()

    def next_track(self) -> None:
        if self.role in {"local", "host"}:
            if self.room is not None:
                self.room.next()
                self._snapshot_dirty = True
                self._refresh_snapshot(force=True)
        elif self.role == "client" and self.client is not None:
            self._client_send({"type": "next"})
        self._drift_corrector.reset()

    def previous_track(self) -> None:
        if self.role in {"local", "host"}:
            if self.room is not None:
                self.room.previous()
                self._snapshot_dirty = True
                self._refresh_snapshot(force=True)
        elif self.role == "client" and self.client is not None:
            self._client_send({"type": "previous"})
        self._drift_corrector.reset()

    def set_volume(self, volume: int) -> None:
        self._ensure_player()
        if self.player is not None:
            self.player.set_volume(volume)

    def cycle_playback_mode(self) -> str:
        modes = ["sequential", "loop", "shuffle"]
        current = str(self.snapshot.get("playback_mode", "sequential"))
        mode = modes[(modes.index(current) + 1) % len(modes)] if current in modes else "sequential"
        if self.role in {"local", "host"}:
            if self.room is not None:
                self.room.set_playback_mode(mode)
                self._snapshot_dirty = True
                self._refresh_snapshot(force=True)
        elif self.role == "client" and self.client is not None:
            self._client_send({"type": "set_playback_mode", "mode": mode})
        return mode

    def remove_queue_item(self, queue_id: str) -> None:
        self.remove_queue_items([queue_id])

    def remove_queue_items(self, queue_ids: list[str]) -> None:
        queue_ids = [str(queue_id) for queue_id in queue_ids if queue_id]
        if not queue_ids:
            return
        if self.role in {"local", "host"}:
            if self.room is not None:
                removed, denied = self.room.remove_tracks(
                    queue_ids,
                    actor_id=self.member_id,
                )
                if removed:
                    self._snapshot_dirty = True
                    self._refresh_snapshot(force=True)
                    self._emit("event", f"已从共享歌单删除 {len(removed)} 首歌曲")
                if denied:
                    self._emit("error", f"有 {len(denied)} 首歌曲无权删除。")
        elif self.role == "client" and self.client is not None:
            self._client_send(
                {"type": "queue_remove_batch", "queue_ids": queue_ids}
            )

    def move_queue_item(self, queue_id: str, before_queue_id: str | None) -> None:
        if self.role in {"local", "host"}:
            if self.room is not None:
                self.room.move_track(queue_id, before_queue_id)
                self._snapshot_dirty = True
                self._refresh_snapshot(force=True)
        elif self.role == "client" and self.client is not None:
            self._client_send(
                {
                    "type": "queue_move",
                    "queue_id": queue_id,
                    "before_queue_id": before_queue_id,
                }
            )

    def play_queue_item(self, queue_id: str) -> None:
        if self.role in {"local", "host"}:
            if self.room is not None:
                self.room.play_queue_item(queue_id)
                self._snapshot_dirty = True
                self._refresh_snapshot(force=True)
        elif self.role == "client" and self.client is not None:
            self._client_send({"type": "queue_play", "queue_id": queue_id})

    def room_info_text(self) -> str:
        return (
            f"房间：{self.snapshot.get('room_name', '一起听歌')}\n"
            f"Radmin IP：{self.host_address}\n"
            f"端口：{self.port}\n"
            f"口令：{self.room_password}"
        )

    def current_media_path(self) -> Path | None:
        track = self._current_track()
        if not track:
            return None
        track_id = str(track["track_id"])
        if self.cache is not None and self.cache.has_track(track_id):
            return self.cache.track_path(track_id)
        return self.library.find_by_track_id(track_id)

    def current_position_ms(self) -> int:
        playback = self.snapshot.get("playback")
        if not isinstance(playback, dict) or not playback.get("track_id"):
            return 0
        if self.role == "client":
            if self.clock is None:
                return int(playback.get("anchor_position_ms", 0))
            try:
                host_now_us = self.clock.host_now_us(monotonic_us())
            except ValueError:
                return int(playback.get("anchor_position_ms", 0))
        else:
            host_now_us = monotonic_us()
        anchor = PlaybackAnchor(
            epoch=int(playback.get("epoch", 0)),
            track_id=str(playback.get("track_id")),
            duration_ms=int(playback.get("duration_ms", 0)),
            playing=bool(playback.get("playing")),
            anchor_position_ms=int(playback.get("anchor_position_ms", 0)),
            anchor_host_us=int(playback.get("anchor_host_us", 0)),
            rate=float(playback.get("rate", 1.0)),
        )
        return self._timeline.target_position_ms(anchor, host_now_us=host_now_us)

    def _start_local_session(self, display_name: str) -> None:
        self.role = "local"
        self.display_name = display_name or "本机"
        self.member_id = "host"
        self.room_password = ""
        self.port = 43871
        self.host_address = ""
        self.connection_status = "本地"
        self.cache = SessionCache(self.data_dir / "cache")
        self.room = HostRoom(room_id="local", room_name="本地播放")
        self.room.add_member(
            self.display_name,
            member_id=self.member_id,
            is_host=True,
        )
        self.server = None
        self.client = None
        self.clock = None
        self._snapshot_dirty = True
        self._loaded_track_id = None
        self._loaded_run_id = None
        self._refresh_snapshot(force=True)

    def _stop_current_session(self) -> None:
        if self.player is not None:
            try:
                self.player.stop()
            except Exception:
                pass
        if self.server is not None:
            self.server.broadcast({"type": "room_closed"})
            time.sleep(0.08)
            self.server.stop()
        if self.client is not None:
            self.client.close()
        if self.cache is not None:
            self.cache.clear()
        self.server = None
        self.client = None
        self.room = None
        self.cache = None
        self.clock = None
        self._pending_downloads.clear()
        self._pending_uploads.clear()
        self._pending_host_requests.clear()
        self._loaded_track_id = None
        self._loaded_run_id = None
        self.snapshot = {}
        self._snapshot_dirty = True

    def _ensure_player(self) -> None:
        if self.player is None:
            self.player = PlaybackController(self._backend_factory())

    def _on_host_connected(
        self,
        requested_member_id: str | None,
        display_name: str,
        reconnected: bool,
    ) -> tuple[str, dict[str, Any]]:
        assert self.room is not None
        member_id = requested_member_id or f"member_{uuid.uuid4().hex}"
        self.room.add_member(
            display_name,
            member_id=member_id,
            is_host=False,
        )
        self._snapshot_dirty = True
        self._event_queue.put(
            (
                "member_connected",
                f"{display_name}{'重新连接' if reconnected else '加入'}了房间",
            )
        )
        return member_id, {"type": "snapshot", "snapshot": self._compose_snapshot()}

    def _on_host_disconnected(self, member_id: str) -> None:
        if self.room is not None:
            self.room.mark_disconnected(member_id)
            for track in self.room.snapshot().get("queue", []):
                if track.get("source_member_id") == member_id:
                    self._pending_host_requests.discard(
                        str(track.get("track_id"))
                    )
            self._snapshot_dirty = True
        if self.server is not None:
            self.server.cancel_uploads(member_id)
        self._event_queue.put(("member_disconnected", "一名成员离线"))

    def _on_host_message(self, member_id: str, message: dict[str, Any]) -> None:
        self._event_queue.put(("host_message", (member_id, message)))

    def _on_host_media_received(
        self,
        member_id: str,
        track_id: str,
        path: Path,
    ) -> None:
        self._event_queue.put(
            ("host_media_received", (member_id, track_id, path))
        )

    def _resolve_host_media(self, track_id: str) -> Path | None:
        if self.cache is not None and self.cache.has_track(track_id):
            return self.cache.track_path(track_id)
        return self.library.find_by_track_id(track_id)

    def _handle_host_message(self, member_id: str, message: dict[str, Any]) -> None:
        if self.room is None or self.server is None:
            return
        message_type = str(message.get("type", ""))
        if message_type == "time_ping":
            t0_us = int(message.get("t0_us", 0))
            now_us = monotonic_us()
            self.server.send_to(
                member_id,
                {
                    "type": "time_pong",
                    "t0_us": t0_us,
                    "t1_us": now_us,
                    "t2_us": monotonic_us(),
                },
            )
            return

        if message_type == "media_ready":
            track_id = str(message.get("track_id", ""))
            self.room.mark_media_ready(member_id, track_id)
            self._snapshot_dirty = True
            return

        if message_type == "media_failed":
            self._pending_host_requests.discard(str(message.get("track_id", "")))
            self._emit("error", str(message.get("message", "成员准备歌曲失败")))
            return

        if message_type == "queue_add":
            if self._accept_queue_add(member_id, message):
                self._snapshot_dirty = True
            return

        if message_type == "queue_add_batch":
            items = message.get("items")
            if not isinstance(items, list):
                self._emit("error", "批量歌曲信息无效。")
                return
            added = False
            for item in items[:QUEUE_BATCH_SIZE]:
                if isinstance(item, dict):
                    added = self._accept_queue_add(member_id, item) or added
            if added:
                self._snapshot_dirty = True
            return

        if message_type == "queue_remove":
            self.room.remove_track(
                str(message.get("queue_id", "")),
                actor_id=member_id,
            )
            self._snapshot_dirty = True
            return

        if message_type == "queue_remove_batch":
            queue_ids = message.get("queue_ids")
            if not isinstance(queue_ids, list):
                self._emit("error", "批量删除信息无效。")
                return
            removed, denied = self.room.remove_tracks(
                [str(queue_id) for queue_id in queue_ids],
                actor_id=member_id,
            )
            if removed:
                self._snapshot_dirty = True
            self.server.send_to(
                member_id,
                {
                    "type": "queue_action_result",
                    "removed": len(removed),
                    "denied": len(denied),
                },
            )
            return

        if message_type == "queue_move":
            before = message.get("before_queue_id")
            self.room.move_track(
                str(message.get("queue_id", "")),
                str(before) if before else None,
            )
            self._snapshot_dirty = True
            return

        if message_type == "queue_play":
            self.room.play_queue_item(str(message.get("queue_id", "")))
            self._snapshot_dirty = True
            return

        if message_type == "set_playback_mode":
            self.room.set_playback_mode(str(message.get("mode", "")))
            self._snapshot_dirty = True
            return

        if message_type == "play_pause":
            if self.room.snapshot()["playback"]["playing"]:
                self.room.pause()
            else:
                self.room.play()
            self._snapshot_dirty = True
            return

        if message_type == "seek":
            self.room.seek(int(message.get("position_ms", 0)))
            self._snapshot_dirty = True
            return

        if message_type == "next":
            self.room.next()
            self._snapshot_dirty = True
            return

        if message_type == "previous":
            self.room.previous()
            self._snapshot_dirty = True
            return

        if message_type == "request_snapshot":
            self.server.send_to(
                member_id,
                {"type": "snapshot", "snapshot": self._compose_snapshot()},
            )

    def _accept_queue_add(
        self,
        member_id: str,
        message: dict[str, Any],
    ) -> bool:
        if self.room is None or self.server is None:
            return False
        track_id = str(message.get("track_id", ""))
        title = str(message.get("title", "")).strip()
        artist = str(message.get("artist", "")).strip()
        duration_ms = int(message.get("duration_ms", 0))
        size_bytes = int(message.get("size_bytes", 0))
        lyrics = str(message.get("lyrics", ""))[:8_000]
        lyrics_lrc = str(message.get("lyrics_lrc", ""))[:8_000]
        if (
            not track_id.startswith("sha256:")
            or not title
            or duration_ms <= 0
            or size_bytes <= 0
            or size_bytes > 500 * 1024 * 1024
        ):
            self._emit("error", "歌曲信息无效，无法加入歌单。")
            return False
        if self.room.has_track(track_id):
            self.server.send_to(
                member_id,
                {"type": "event", "message": f"歌单中已有《{title}》"},
            )
            return False
        self.room.add_track(
            member_id=member_id,
            track_id=track_id,
            title=title,
            artist=artist,
            duration_ms=duration_ms,
            size_bytes=size_bytes,
            lyrics=lyrics,
            lyrics_lrc=lyrics_lrc,
        )
        return True
    def _handle_client_message(self, message: dict[str, Any]) -> None:
        message_type = str(message.get("type", ""))
        if message_type == "snapshot":
            snapshot = message.get("snapshot")
            if isinstance(snapshot, dict):
                self.snapshot = snapshot
                self._snapshot_received_at = time.monotonic()
                self.connection_status = "已同步"
                self._emit("snapshot", snapshot)
            return

        if message_type == "transfer_request":
            track_id = str(message.get("track_id", ""))
            path = self.library.find_by_track_id(track_id)
            if path is None:
                self._client_send(
                    {
                        "type": "media_failed",
                        "track_id": track_id,
                        "message": "本机找不到源文件。",
                    }
                )
                return
            current = self._current_track()
            if current and current.get("track_id") == track_id:
                self._client_send({"type": "media_ready", "track_id": track_id})
            if track_id not in self._pending_uploads:
                self._pending_uploads.add(track_id)
                threading.Thread(
                    target=self._upload_worker,
                    args=(track_id, path),
                    name="upload-track",
                    daemon=True,
                ).start()
            return

        if message_type == "queue_action_result":
            removed = int(message.get("removed", 0))
            denied = int(message.get("denied", 0))
            if removed:
                self._emit("event", f"已从共享歌单删除 {removed} 首歌曲")
            if denied:
                self._emit("error", f"有 {denied} 首歌曲无权删除。")
            return

        if message_type == "heartbeat":
            return

        if message_type == "time_pong":
            if self.clock is None:
                return
            t3_us = monotonic_us()
            try:
                self.clock.add_sample(
                    t0_us=int(message["t0_us"]),
                    t1_us=int(message["t1_us"]),
                    t2_us=int(message["t2_us"]),
                    t3_us=t3_us,
                )
            except (KeyError, ValueError):
                return
            return

        if message_type == "error":
            self._emit("error", str(message.get("message", "房间发生错误")))
            return

        if message_type == "event":
            self._emit("event", str(message.get("message", "")))
            return

        if message_type == "room_closed":
            self._event_queue.put(("room_closed", None))

    def _handle_event(self, kind: str, payload: Any) -> None:
        if kind == "library_scanned":
            self._emit("library_updated", self.library.tracks())
        elif kind == "track_hashed":
            media, track_id = payload
            self._add_tracks_with_ids([(media, track_id)])
        elif kind == "tracks_hashed":
            self._add_tracks_with_ids(payload)
        elif kind == "host_message":
            self._handle_host_message(*payload)
        elif kind == "host_media_received":
            _member_id, track_id, _path = payload
            self._pending_host_requests.discard(track_id)
            self._snapshot_dirty = True
            self._emit("event", "歌曲已准备完成")
        elif kind == "client_message":
            self._handle_client_message(payload)
        elif kind == "client_disconnected":
            self.connection_status = "正在重连"
            self._emit("connection", self.connection_status)
        elif kind == "client_reconnected":
            self.connection_status = "已连接"
            self._emit("connection", self.connection_status)
            self._send_clock_ping()
        elif kind == "download_complete":
            track_id, _path = payload
            self._pending_downloads.discard(track_id)
            current = self._current_track()
            if current and current.get("track_id") == track_id:
                self._client_send({"type": "media_ready", "track_id": track_id})
            self._emit("event", "歌曲下载完成")
        elif kind == "download_failed":
            track_id, message = payload
            self._pending_downloads.discard(track_id)
            self._emit("error", f"歌曲下载失败：{message}")
        elif kind == "upload_failed":
            track_id, message = payload
            self._pending_uploads.discard(track_id)
            self._emit("error", f"歌曲上传失败：{message}")
        elif kind == "upload_complete":
            track_id = payload
            self._pending_uploads.discard(track_id)
        elif kind == "member_connected":
            self._emit("event", payload)
        elif kind == "member_disconnected":
            self._emit("event", payload)
        elif kind == "room_closed":
            self.connection_status = "房间已关闭"
            self._emit("error", "房主已关闭房间")
            self.leave_room()
        elif kind == "error":
            self._emit("error", payload)

    def _add_track_with_id(self, media: MediaFile, track_id: str) -> None:
        self._add_tracks_with_ids([(media, track_id)])

    def _add_tracks_with_ids(
        self,
        pairs: list[tuple[MediaFile, str]],
    ) -> None:
        if not pairs:
            return
        if self.role == "client":
            queued_ids = {
                str(item.get("track_id", ""))
                for item in self.snapshot.get("queue", [])
            }
            pending: list[dict[str, Any]] = []
            for media, track_id in pairs:
                if track_id in queued_ids:
                    self._emit("event", f"歌单中已有《{media.title}》")
                    continue
                queued_ids.add(track_id)
                pending.append(self._media_queue_payload(media, track_id))
            for offset in range(0, len(pending), QUEUE_BATCH_SIZE):
                self._client_send(
                    {
                        "type": "queue_add_batch",
                        "items": pending[offset : offset + QUEUE_BATCH_SIZE],
                    }
                )
            return
        if self.room is None:
            return
        added = False
        for media, track_id in pairs:
            if self.room.has_track(track_id):
                self._emit("event", f"歌单中已有《{media.title}》")
                continue
            self.room.add_track(
                member_id=self.member_id,
                track_id=track_id,
                title=media.title,
                artist=media.artist,
                duration_ms=media.duration_ms,
                size_bytes=media.size_bytes,
                lyrics=media.lyrics[:8_000],
                lyrics_lrc=media.lyrics_lrc[:8_000],
            )
            added = True
        if added:
            self._snapshot_dirty = True
            self._refresh_snapshot(force=True)

    @staticmethod
    def _media_queue_payload(media: MediaFile, track_id: str) -> dict[str, Any]:
        return {
            "track_id": track_id,
            "title": media.title,
            "artist": media.artist,
            "duration_ms": media.duration_ms,
            "size_bytes": media.size_bytes,
            "lyrics": media.lyrics[:8_000],
            "lyrics_lrc": media.lyrics_lrc[:8_000],
        }

    def _prepare_host_media(self, *, include_prefetch: bool) -> None:
        if self.room is None:
            return
        current = self.room.current_track
        next_track = self.room.next_track
        if current is not None:
            path = self._resolve_host_media(current.track_id)
            if path is not None:
                self.room.mark_media_ready(self.member_id, current.track_id)
            elif (
                current.source_member_id != self.member_id
                and self.server is not None
                and current.track_id not in self._pending_host_requests
            ):
                self._pending_host_requests.add(current.track_id)
                self.server.expect_upload(
                    current.source_member_id,
                    current.track_id,
                    current.size_bytes,
                )
                self.server.send_to(
                    current.source_member_id,
                    {"type": "transfer_request", "track_id": current.track_id},
                )
        if (
            include_prefetch
            and
            next_track is not None
            and self._resolve_host_media(next_track.track_id) is None
            and next_track.source_member_id != self.member_id
            and self.server is not None
            and next_track.track_id not in self._pending_host_requests
        ):
            self._pending_host_requests.add(next_track.track_id)
            self.server.expect_upload(
                next_track.source_member_id,
                next_track.track_id,
                next_track.size_bytes,
            )
            self.server.send_to(
                next_track.source_member_id,
                {"type": "transfer_request", "track_id": next_track.track_id},
            )

    def _prepare_client_media(self, *, include_prefetch: bool) -> None:
        if self.client is None or self.cache is None:
            return
        current = self._current_track()
        if current is not None:
            self._prepare_client_track(current, mark_ready=True)
        prefetch_id = self.snapshot.get("prefetch_track_id")
        if include_prefetch and prefetch_id:
            prefetch = next(
                (
                    item
                    for item in self.snapshot.get("queue", [])
                    if item.get("track_id") == prefetch_id
                ),
                None,
            )
            if prefetch is not None:
                self._prepare_client_track(prefetch, mark_ready=False)

    def _can_prefetch_full_next(self) -> bool:
        current = self._current_track()
        if current is None:
            return False
        track_id = str(current.get("track_id", ""))
        return bool(
            self.player is not None
            and self._loaded_track_id == track_id
        )

    def _prepare_client_track(
        self,
        track: dict[str, Any],
        *,
        mark_ready: bool,
    ) -> None:
        track_id = str(track["track_id"])
        path = self._resolve_client_media(track_id)
        if path is not None:
            if mark_ready:
                member = self._current_member()
                if member and member.get("ready_track_id") != track_id:
                    self._client_send({"type": "media_ready", "track_id": track_id})
            return
        host_has_media = (
            self.snapshot.get("host_has_media")
            if mark_ready
            else self.snapshot.get("prefetch_host_has_media")
        )
        if not host_has_media or track_id in self._pending_downloads:
            return
        size_bytes = int(track.get("size_bytes", 0))
        if size_bytes <= 0:
            return
        self._pending_downloads.add(track_id)
        threading.Thread(
            target=self._download_worker,
            args=(track_id, size_bytes),
            name="download-track",
            daemon=True,
        ).start()

    def _resolve_client_media(self, track_id: str) -> Path | None:
        if self.cache is not None and self.cache.has_track(track_id):
            return self.cache.track_path(track_id)
        return self.library.find_by_track_id(track_id)

    def _download_worker(self, track_id: str, size_bytes: int) -> None:
        assert self.cache is not None
        assert self.client is not None
        part = self.cache.part_path(track_id)
        try:
            self.cache.reserve(track_id, size_bytes)
            self.client.download_track(
                track_id=track_id,
                part_path=part,
                expected_size=size_bytes,
            )
            stored = self.cache.finalize_part(
                part,
                track_id=track_id,
                expected_hash=track_id,
                expected_size=size_bytes,
            )
            self._event_queue.put(("download_complete", (track_id, stored)))
        except (CacheFullError, OSError, RuntimeError, ValueError) as error:
            part.unlink(missing_ok=True)
            self._event_queue.put(("download_failed", (track_id, str(error))))
        finally:
            self.cache.release_reservation(track_id)

    def _upload_worker(self, track_id: str, path: Path) -> None:
        try:
            if self.client is None:
                raise ConnectionError("Not connected.")
            self.client.upload_track(track_id=track_id, path=path)
            self._event_queue.put(("upload_complete", track_id))
        except (OSError, RuntimeError) as error:
            self._event_queue.put(("upload_failed", (track_id, str(error))))

    def _sync_playback(self) -> None:
        playback = self.snapshot.get("playback")
        if not isinstance(playback, dict) or not playback.get("track_id"):
            self._stop_loaded_media()
            return
        track_id = str(playback["track_id"])
        run_id = int(playback.get("run_id", 0))
        path = self.current_media_path()
        if path is None:
            if self._loaded_track_id != track_id:
                self._stop_loaded_media()
            return
        self._ensure_player()
        if self.player is None:
            return
        if self._loaded_track_id != track_id or self._loaded_run_id != run_id:
            self._stop_loaded_media()
            try:
                self.player.load(path)
                self._loaded_track_id = track_id
                self._loaded_run_id = run_id
                self._drift_hits = 0
            except Exception as error:
                self._emit("error", f"播放器加载失败：{error}")
                return

        if self.role == "client":
            if self.clock is None:
                return
            try:
                host_now_us = self.clock.host_now_us(monotonic_us())
            except ValueError:
                return
        else:
            host_now_us = monotonic_us()

        anchor = PlaybackAnchor(
            epoch=int(playback.get("epoch", 0)),
            track_id=track_id,
            duration_ms=int(playback.get("duration_ms", 0)),
            playing=bool(playback.get("playing")),
            anchor_position_ms=int(playback.get("anchor_position_ms", 0)),
            anchor_host_us=int(playback.get("anchor_host_us", 0)),
            rate=float(playback.get("rate", 1.0)),
        )
        target_ms = self._timeline.target_position_ms(
            anchor,
            host_now_us=host_now_us,
        )

        if not anchor.playing:
            if self.player.state.value == "playing":
                self.player.pause()
            if abs(self.player.position_ms() - anchor.anchor_position_ms) > 120:
                self.player.seek_ms(anchor.anchor_position_ms)
            return

        if host_now_us < anchor.anchor_host_us:
            if self.player.state.value == "playing":
                self.player.pause()
            if abs(self.player.position_ms() - anchor.anchor_position_ms) > 80:
                self.player.seek_ms(anchor.anchor_position_ms)
            return

        if self.player.state.value != "playing":
            self.player.seek_ms(target_ms)
            self.player.play()
            self._drift_corrector.reset()
            return

        drift_ms = self.player.position_ms() - target_ms
        if self._drift_corrector.update(drift_ms, now_s=time.monotonic()):
            self.player.seek_ms(target_ms)

    def _stop_loaded_media(self) -> None:
        if self.player is not None and self._loaded_track_id is not None:
            try:
                self.player.stop()
            except Exception:
                pass
        self._loaded_track_id = None
        self._loaded_run_id = None
        self._drift_corrector.reset()

    def _compose_snapshot(self) -> dict[str, Any]:
        if self.room is None:
            return {}
        snapshot = self.room.snapshot()
        current = self.room.current_track
        next_track = self.room.next_track
        snapshot["host_has_media"] = bool(
            current and self._resolve_host_media(current.track_id)
        )
        snapshot["prefetch_host_media"] = bool(
            next_track and self._resolve_host_media(next_track.track_id)
        )
        snapshot["role"] = self.role
        snapshot["host_address"] = self.host_address
        snapshot["port"] = self.port
        return snapshot

    def _refresh_snapshot(self, *, force: bool = False) -> None:
        if self.room is None:
            return
        snapshot = self._compose_snapshot()
        signature_snapshot = dict(snapshot)
        signature_snapshot.pop("listening_ms", None)
        signature = json.dumps(signature_snapshot, ensure_ascii=False, sort_keys=True)
        changed = signature != self._last_snapshot_signature
        self.snapshot = snapshot
        self._snapshot_received_at = time.monotonic()
        if changed or force:
            self._last_snapshot_signature = signature
            self._emit("snapshot", snapshot)
            if self.server is not None:
                self.server.broadcast({"type": "snapshot", "snapshot": snapshot})
                self._last_broadcast_at = time.monotonic()
            self._snapshot_dirty = False
        elif self.server is not None and time.monotonic() - self._last_broadcast_at >= 5:
            self.server.broadcast(
                {
                    "type": "heartbeat",
                    "queue_revision": int(snapshot.get("queue_revision", 0)),
                }
            )
            self._last_broadcast_at = time.monotonic()

    def listening_time_ms(self) -> int:
        base_ms = int(self.snapshot.get("listening_ms", 0))
        playback = self.snapshot.get("playback", {})
        if isinstance(playback, dict) and playback.get("playing"):
            base_ms += int((time.monotonic() - self._snapshot_received_at) * 1_000)
        return max(0, base_ms)
    def _update_cache_pins(self) -> None:
        if self.cache is None:
            return
        queue_items = self.snapshot.get("queue", [])
        current_index = int(self.snapshot.get("current_index", -1))
        keep: set[str] = set()
        for index in (current_index - 1, current_index, current_index + 1):
            if 0 <= index < len(queue_items):
                keep.add(str(queue_items[index]["track_id"]))
        keep.update(
            str(track_id)
            for track_id in self.snapshot.get("history_track_ids", [])
        )
        if self.room is not None:
            for track in (self.room.current_track, self.room.next_track):
                if track is not None:
                    keep.add(track.track_id)
        keep.update(self._pending_downloads)
        keep.update(self._pending_host_requests)
        self.cache.set_pinned_track_ids(keep)

    def _prune_cache(self) -> None:
        if self.cache is None:
            return
        self._update_cache_pins()
        self.cache.prune_to_limit()

    def _send_clock_ping(self) -> None:
        if self.role != "client" or self.client is None or not self.client.connected:
            return
        self._last_ping_at = time.monotonic()
        self._client_send({"type": "time_ping", "t0_us": monotonic_us()})

    def _maybe_send_clock_ping(self) -> None:
        if time.monotonic() - self._last_ping_at >= 10:
            self._send_clock_ping()

    def _client_send(self, message: dict[str, Any]) -> None:
        if self.client is None:
            return
        try:
            self.client.send(message)
        except (ConnectionError, OSError) as error:
            self._emit("error", f"发送房间指令失败：{error}")

    def _current_track(self) -> dict[str, Any] | None:
        queue_items = self.snapshot.get("queue", [])
        index = int(self.snapshot.get("current_index", -1))
        if 0 <= index < len(queue_items):
            return queue_items[index]
        return None

    def _current_member(self) -> dict[str, Any] | None:
        return next(
            (
                member
                for member in self.snapshot.get("members", [])
                if member.get("member_id") == self.member_id
            ),
            None,
        )

    def _drain_events(self) -> None:
        while True:
            try:
                kind, payload = self._event_queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._handle_event(kind, payload)
            except Exception as error:
                self._emit("error", str(error))

    def _deliver_events(self) -> None:
        while True:
            try:
                kind, payload = self._event_queue.get_nowait()
            except queue.Empty:
                return
            self._emit(kind, payload)

    def _emit(self, kind: str, payload: Any) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(kind, payload)
        except Exception:
            pass
