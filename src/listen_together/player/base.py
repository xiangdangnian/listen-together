from enum import Enum
from pathlib import Path
from typing import Protocol


class PlaybackState(str, Enum):
    IDLE = "idle"
    READY = "ready"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


class PlayerBackend(Protocol):
    def open(self, path: Path) -> int:
        """Open a media file and return its duration in milliseconds."""

    def play(self) -> None:
        """Start or resume playback."""

    def pause(self) -> None:
        """Pause playback."""

    def seek_ms(self, position_ms: int) -> None:
        """Seek to an absolute media position."""

    def position_ms(self) -> int:
        """Return the current media position."""

    def is_playing(self) -> bool:
        """Return whether the backend is currently playing."""

    def set_rate(self, rate: float) -> None:
        """Set the playback rate."""

    def set_volume(self, volume: int) -> None:
        """Set local output volume from 0 to 100."""

    def stop(self) -> None:
        """Stop playback and release the current media."""

    def close(self) -> None:
        """Release all backend resources."""

