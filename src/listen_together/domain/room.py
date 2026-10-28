import random
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from listen_together.domain.models import Member, Playback, QueueTrack
from listen_together.sync.timeline import PlaybackAnchor, Timeline


def monotonic_us() -> int:
    return time.monotonic_ns() // 1_000


class HostRoom:
    START_DELAY_US = 600_000

    def __init__(
        self,
        *,
        room_id: str,
        room_name: str,
        now_us: Callable[[], int] = monotonic_us,
    ) -> None:
        self.room_id = room_id
        self.room_name = room_name
        self._now_us = now_us
        self._timeline = Timeline()
        self._lock = threading.RLock()
        self._members: dict[str, Member] = {}
        self._queue: list[QueueTrack] = []
        self._current_index = -1
        self._playback = Playback()
        self._queue_revision = 0
        self._paused_by_user = False
        self._playback_mode = "sequential"
        self._history: list[QueueTrack] = []
        self._listening_ms = 0.0
        self._last_account_us = self._now_us()

    @property
    def host_member_id(self) -> str | None:
        for member in self._members.values():
            if member.is_host:
                return member.member_id
        return None

    def add_member(
        self,
        display_name: str,
        *,
        member_id: str | None = None,
        is_host: bool = False,
    ) -> Member:
        with self._lock:
            resolved_id = member_id or f"member_{uuid.uuid4().hex}"
            existing = self._members.get(resolved_id)
            if existing is not None:
                existing.display_name = display_name
                existing.connected = True
                existing.ready_track_id = None
                member = existing
            else:
                member = Member(
                    member_id=resolved_id,
                    display_name=display_name,
                    is_host=is_host,
                )
                self._members[resolved_id] = member

            if self.current_track is not None:
                self._pause_for_waiting()
            return member

    def mark_disconnected(self, member_id: str) -> None:
        with self._lock:
            member = self._members.get(member_id)
            if member is None:
                return
            member.connected = False
            member.ready_track_id = None

    def remove_member(self, member_id: str) -> None:
        with self._lock:
            self._members.pop(member_id, None)

    @property
    def current_track(self) -> QueueTrack | None:
        with self._lock:
            if 0 <= self._current_index < len(self._queue):
                return self._queue[self._current_index]
            return None

    @property
    def next_track(self) -> QueueTrack | None:
        with self._lock:
            next_index = self._current_index + 1
            if 0 <= next_index < len(self._queue):
                return self._queue[next_index]
            return None

    def has_track(self, track_id: str) -> bool:
        with self._lock:
            return any(track.track_id == track_id for track in self._queue)
    def add_track(
        self,
        *,
        member_id: str,
        track_id: str,
        title: str,
        artist: str,
        duration_ms: int,
        size_bytes: int,
        lyrics: str = "",
        lyrics_lrc: str = "",
    ) -> QueueTrack:
        with self._lock:
            track = QueueTrack(
                queue_id=f"queue_{uuid.uuid4().hex}",
                track_id=track_id,
                source_member_id=member_id,
                added_by=member_id,
                title=title,
                artist=artist,
                duration_ms=max(1, duration_ms),
                size_bytes=max(0, size_bytes),
                lyrics=lyrics[:8_000],
                lyrics_lrc=lyrics_lrc[:8_000],
            )
            self._queue.append(track)
            self._queue_revision += 1
            if self._current_index < 0:
                self._begin_current(0)
            return track

    def remove_track(self, queue_id: str, *, actor_id: str) -> bool:
        with self._lock:
            self._account_playback_time()
            for index, track in enumerate(self._queue):
                if track.queue_id != queue_id:
                    continue
                if actor_id != track.added_by and actor_id != self.host_member_id:
                    return False

                was_current = index == self._current_index
                self._queue.pop(index)
                self._queue_revision += 1
                if not self._queue:
                    self._current_index = -1
                    self._reset_playback()
                elif was_current:
                    self._begin_current(min(index, len(self._queue) - 1))
                elif index < self._current_index:
                    self._current_index -= 1
                return True
            return False

    def remove_tracks(
        self,
        queue_ids: list[str],
        *,
        actor_id: str,
    ) -> tuple[list[str], list[str]]:
        requested = {str(queue_id) for queue_id in queue_ids}
        if not requested:
            return [], []
        with self._lock:
            self._account_playback_time()
            current = self.current_track
            previous_index = self._current_index
            kept: list[QueueTrack] = []
            removed: list[str] = []
            denied: list[str] = []
            for track in self._queue:
                if track.queue_id not in requested:
                    kept.append(track)
                elif actor_id == track.added_by or actor_id == self.host_member_id:
                    removed.append(track.queue_id)
                else:
                    denied.append(track.queue_id)
            if not removed:
                return [], denied
            self._queue = kept
            self._queue_revision += 1
            if not self._queue:
                self._current_index = -1
                self._reset_playback()
            elif current is not None and current.queue_id not in set(removed):
                self._current_index = next(
                    index
                    for index, track in enumerate(self._queue)
                    if track.queue_id == current.queue_id
                )
            else:
                self._begin_current(min(max(previous_index, 0), len(self._queue) - 1))
            return removed, denied
    def move_track(self, queue_id: str, before_queue_id: str | None) -> bool:
        with self._lock:
            current = self.current_track
            source_index = next(
                (index for index, track in enumerate(self._queue) if track.queue_id == queue_id),
                None,
            )
            if source_index is None:
                return False

            track = self._queue.pop(source_index)
            if before_queue_id is None:
                target_index = len(self._queue)
            else:
                target_index = next(
                    (
                        index
                        for index, candidate in enumerate(self._queue)
                        if candidate.queue_id == before_queue_id
                    ),
                    len(self._queue),
                )
            self._queue.insert(target_index, track)
            self._queue_revision += 1
            if current is not None:
                self._current_index = self._queue.index(current)
            return True

    def play_queue_item(self, queue_id: str) -> bool:
        with self._lock:
            index = next(
                (
                    index
                    for index, track in enumerate(self._queue)
                    if track.queue_id == queue_id
                ),
                None,
            )
            if index is None:
                return False
            self._begin_current(index)
            return True

    def mark_media_ready(self, member_id: str, track_id: str) -> None:
        with self._lock:
            member = self._members.get(member_id)
            if member is None or not member.connected:
                return
            member.ready_track_id = track_id

    def clear_media_ready(self) -> None:
        with self._lock:
            for member in self._members.values():
                member.ready_track_id = None

    def all_online_ready(self) -> bool:
        with self._lock:
            track = self.current_track
            connected = [member for member in self._members.values() if member.connected]
            return bool(
                track
                and connected
                and all(member.ready_track_id == track.track_id for member in connected)
            )

    def current_position_ms(self) -> int:
        with self._lock:
            if self._playback.track_id is None:
                return 0
            anchor = PlaybackAnchor(
                epoch=self._playback.epoch,
                track_id=self._playback.track_id,
                duration_ms=self._playback.duration_ms,
                playing=self._playback.playing,
                anchor_position_ms=self._playback.anchor_position_ms,
                anchor_host_us=self._playback.anchor_host_us,
                rate=self._playback.rate,
            )
            return self._timeline.target_position_ms(
                anchor,
                host_now_us=self._now_us(),
            )

    def pause(self) -> None:
        with self._lock:
            self._account_playback_time()
            if self.current_track is None:
                return
            position_ms = self.current_position_ms()
            self._playback.anchor_position_ms = position_ms
            self._playback.anchor_host_us = self._now_us()
            self._playback.playing = False
            self._playback.epoch += 1
            self._paused_by_user = True

    def play(self) -> None:
        with self._lock:
            if self.current_track is None or not self.all_online_ready():
                return
            self._start_current_from(self.current_position_ms())
            self._paused_by_user = False

    def seek(self, position_ms: int) -> None:
        with self._lock:
            self._account_playback_time()
            track = self.current_track
            if track is None:
                return
            target_ms = min(max(0, int(position_ms)), track.duration_ms)
            self._playback.anchor_position_ms = target_ms
            self._playback.anchor_host_us = self._now_us()
            self._playback.epoch += 1

    def next(self) -> None:
        with self._lock:
            self._advance(natural_end=False)
    def previous(self) -> None:
        with self._lock:
            self._account_playback_time()
            if not self._queue:
                if self._history:
                    track = self._history.pop()
                    self._queue.append(track)
                    self._queue_revision += 1
                    self._begin_current(0)
                return
            if self._playback_mode == "shuffle" and len(self._queue) > 1:
                candidates = [
                    index
                    for index in range(len(self._queue))
                    if index != self._current_index
                ]
                self._begin_current(random.choice(candidates))
            elif self._current_index > 0:
                self._begin_current(self._current_index - 1)
            elif self._history:
                track = self._history.pop()
                insert_index = max(0, self._current_index)
                self._queue.insert(insert_index, track)
                self._queue_revision += 1
                self._begin_current(insert_index)
            elif self._playback_mode == "loop":
                self._begin_current(len(self._queue) - 1)
    def set_playback_mode(self, mode: str) -> bool:
        if mode not in {"sequential", "loop", "shuffle"}:
            return False
        with self._lock:
            self._playback_mode = mode
            return True

    def tick(self) -> None:
        with self._lock:
            self._account_playback_time()
            track = self.current_track
            if track is None:
                return

            if self._playback.playing and self.current_position_ms() >= track.duration_ms:
                self._advance(natural_end=True)
                return

            if (
                not self._playback.playing
                and not self._paused_by_user
                and self.all_online_ready()
                and self._playback.anchor_position_ms < track.duration_ms
            ):
                self._start_current_from(self._playback.anchor_position_ms)

    def _advance(self, *, natural_end: bool) -> None:
        self._account_playback_time()
        if not self._queue:
            return
        current = self.current_track
        if (
            natural_end
            and self._playback_mode == "sequential"
            and current is not None
        ):
            self._history.append(current)
            del self._history[:-10]
            remove_index = self._current_index
            self._queue.pop(remove_index)
            self._queue_revision += 1
            if not self._queue or remove_index >= len(self._queue):
                self._current_index = -1
                self._reset_playback()
            else:
                self._begin_current(remove_index)
            return

        if self._playback_mode == "shuffle" and len(self._queue) > 1:
            candidates = [
                index
                for index in range(len(self._queue))
                if index != self._current_index
            ]
            self._begin_current(random.choice(candidates))
        elif self._current_index + 1 < len(self._queue):
            self._begin_current(self._current_index + 1)
        elif self._playback_mode == "loop":
            self._begin_current(0)
        elif current is not None:
            self._playback.anchor_position_ms = current.duration_ms
            self._playback.anchor_host_us = self._now_us()
            self._playback.playing = False
            self._playback.epoch += 1
            self._paused_by_user = True
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            track = self.current_track
            queue = [item.to_dict() for item in self._queue]
            if track is not None and 0 <= self._current_index < len(queue):
                queue[self._current_index]["lyrics"] = track.lyrics
                queue[self._current_index]["lyrics_lrc"] = track.lyrics_lrc
            return {
                "room_id": self.room_id,
                "room_name": self.room_name,
                "queue_revision": self._queue_revision,
                "queue": queue,
                "current_index": self._current_index,
                "current_track_id": track.track_id if track else None,
                "prefetch_track_id": self.next_track.track_id if self.next_track else None,
                "members": [member.to_dict() for member in self._members.values()],
                "playback": self._playback.to_dict(),
                "playback_mode": self._playback_mode,
                "all_online_ready": self.all_online_ready(),
                "listening_ms": int(self._listening_ms),
                "history_track_ids": [
                    item.track_id for item in self._history[-1:]
                ],
            }

    def _begin_current(self, index: int) -> None:
        self._current_index = index
        if not self._queue:
            self._reset_playback()
            return
        track = self._queue[index]
        self._playback = Playback(
            epoch=self._playback.epoch + 1,
            run_id=self._playback.run_id + 1,
            track_id=track.track_id,
            duration_ms=track.duration_ms,
            playing=False,
            anchor_position_ms=0,
            anchor_host_us=self._now_us(),
        )
        self._paused_by_user = False
        for member in self._members.values():
            member.ready_track_id = None

    def _reset_playback(self) -> None:
        self._playback = Playback(
            epoch=self._playback.epoch + 1,
            run_id=self._playback.run_id + 1,
        )
        self._paused_by_user = False
        for member in self._members.values():
            member.ready_track_id = None

    def _account_playback_time(self) -> None:
        now_us = self._now_us()
        if self._playback.playing:
            start_us = max(self._last_account_us, self._playback.anchor_host_us)
            if now_us > start_us:
                self._listening_ms += (now_us - start_us) / 1_000
        self._last_account_us = now_us

    def _pause_for_waiting(self) -> None:
        self._account_playback_time()
        position_ms = self.current_position_ms()
        self._playback.anchor_position_ms = position_ms
        self._playback.anchor_host_us = self._now_us()
        self._playback.playing = False
        self._playback.epoch += 1
        self._paused_by_user = False

    def _start_current_from(self, position_ms: int) -> None:
        start_at_us = self._now_us() + self.START_DELAY_US
        self._playback.anchor_position_ms = position_ms
        self._playback.anchor_host_us = start_at_us
        self._playback.playing = True
        self._playback.epoch += 1
