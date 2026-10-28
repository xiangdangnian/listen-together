from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MediaFile:
    path: Path
    title: str
    artist: str
    album: str
    duration_ms: int
    size_bytes: int
    track_id: str | None = None
    lyrics: str = ""
    lyrics_lrc: str = ""

    @property
    def display_name(self) -> str:
        if self.artist:
            return f"{self.artist} - {self.title}"
        return self.title

