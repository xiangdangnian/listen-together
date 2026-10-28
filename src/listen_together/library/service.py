import threading
from pathlib import Path

from listen_together.library.cache import LibraryCache
from listen_together.library.models import MediaFile
from listen_together.library.scanner import (
    compute_sha256,
    iter_audio_paths,
    read_media_file,
)


class LibraryService:
    def __init__(self, cache: LibraryCache) -> None:
        self._cache = cache
        self._lock = threading.RLock()
        self._tracks: dict[Path, MediaFile] = {}

    def scan_directory(self, directory: Path) -> list[MediaFile]:
        root = Path(directory).resolve()
        with self._lock:
            self._tracks.clear()
        self._cache.remove_tracks_outside(root)
        scanned: list[MediaFile] = []
        pending_upserts: list[tuple[MediaFile, int]] = []
        for path in iter_audio_paths(root):
            try:
                stat = path.stat()
                media = self._cache.get(
                    path,
                    mtime_ns=stat.st_mtime_ns,
                    size_bytes=stat.st_size,
                )
                if (
                    media is None
                    or media.duration_ms <= 100
                    or (media.lyrics and not media.lyrics_lrc)
                ):
                    media = read_media_file(path)
                    pending_upserts.append((media, stat.st_mtime_ns))
                    if len(pending_upserts) >= 50:
                        self._cache.upsert_many(pending_upserts)
                        pending_upserts.clear()
                with self._lock:
                    self._tracks[media.path] = media
                scanned.append(media)
            except (OSError, ValueError):
                continue
        self._cache.upsert_many(pending_upserts)
        return scanned

    def tracks(self) -> list[MediaFile]:
        with self._lock:
            return sorted(
                self._tracks.values(),
                key=lambda media: (
                    media.artist.casefold(),
                    media.title.casefold(),
                ),
            )

    def search(self, query: str) -> list[MediaFile]:
        needle = query.strip().casefold()
        if not needle:
            return self.tracks()
        return [
            media
            for media in self.tracks()
            if needle in media.title.casefold()
            or needle in media.artist.casefold()
            or needle in media.album.casefold()
        ]

    def compute_track_id(self, path: Path) -> str:
        resolved_path = Path(path).resolve()
        cached_path = None
        with self._lock:
            media = self._tracks.get(resolved_path)
            if media is not None and media.track_id:
                return media.track_id
        track_id = compute_sha256(resolved_path)
        with self._lock:
            if media is not None:
                updated = MediaFile(
                    path=media.path,
                    title=media.title,
                    artist=media.artist,
                    album=media.album,
                    duration_ms=media.duration_ms,
                    size_bytes=media.size_bytes,
                    track_id=track_id,
                    lyrics=media.lyrics,
                    lyrics_lrc=media.lyrics_lrc,
                )
                self._tracks[resolved_path] = updated
                cached_path = updated.path
        if cached_path is not None:
            self._cache.set_track_id(cached_path, track_id)
        return track_id

    def find_by_track_id(self, track_id: str) -> Path | None:
        with self._lock:
            for media in self._tracks.values():
                if media.track_id == track_id and media.path.is_file():
                    return media.path
        cached = self._cache.find_path_by_track_id(track_id)
        if cached and cached.is_file():
            return cached.resolve()
        return None

    def find_matching_track(
        self,
        track_id: str,
        *,
        title: str,
        duration_ms: int,
        size_bytes: int,
    ) -> Path | None:
        candidates = [
            media
            for media in self.tracks()
            if media.size_bytes == size_bytes
            and abs(media.duration_ms - duration_ms) <= 1_000
            and media.title.casefold() == title.casefold()
        ]
        for media in candidates:
            if self.compute_track_id(media.path) == track_id:
                return media.path
        return None

    def close(self) -> None:
        self._cache.close()
