from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Member:
    member_id: str
    display_name: str
    connected: bool = True
    ready_track_id: str | None = None
    is_host: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "display_name": self.display_name,
            "connected": self.connected,
            "ready_track_id": self.ready_track_id,
            "is_host": self.is_host,
        }


@dataclass(slots=True)
class QueueTrack:
    queue_id: str
    track_id: str
    source_member_id: str
    added_by: str
    title: str
    artist: str
    duration_ms: int
    size_bytes: int
    lyrics: str = ""
    lyrics_lrc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_id": self.queue_id,
            "track_id": self.track_id,
            "source_member_id": self.source_member_id,
            "added_by": self.added_by,
            "title": self.title,
            "artist": self.artist,
            "duration_ms": self.duration_ms,
            "size_bytes": self.size_bytes,
        }


@dataclass(slots=True)
class Playback:
    epoch: int = 0
    run_id: int = 0
    track_id: str | None = None
    duration_ms: int = 0
    playing: bool = False
    anchor_position_ms: int = 0
    anchor_host_us: int = 0
    rate: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "epoch": self.epoch,
            "run_id": self.run_id,
            "track_id": self.track_id,
            "duration_ms": self.duration_ms,
            "playing": self.playing,
            "anchor_position_ms": self.anchor_position_ms,
            "anchor_host_us": self.anchor_host_us,
            "rate": self.rate,
        }
