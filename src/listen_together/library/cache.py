import sqlite3
import threading
from pathlib import Path

from listen_together.library.models import MediaFile


class LibraryCache:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            str(database_path),
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tracks (
                    path TEXT PRIMARY KEY,
                    mtime_ns INTEGER NOT NULL,
                    size INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    album TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    track_id TEXT
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS tracks_track_id ON tracks(track_id)"
            )
            self._connection.commit()

    def get(
        self,
        path: Path,
        *,
        mtime_ns: int,
        size_bytes: int,
    ) -> MediaFile | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM tracks WHERE path = ?",
                (str(path),),
            ).fetchone()
        if row is None or row["mtime_ns"] != mtime_ns or row["size"] != size_bytes:
            return None
        return MediaFile(
            path=Path(row["path"]),
            title=row["title"],
            artist=row["artist"],
            album=row["album"],
            duration_ms=row["duration_ms"],
            size_bytes=row["size"],
            track_id=row["track_id"],
        )

    def upsert(self, media: MediaFile, *, mtime_ns: int) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO tracks (
                    path, mtime_ns, size, title, artist, album, duration_ms, track_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    mtime_ns = excluded.mtime_ns,
                    size = excluded.size,
                    title = excluded.title,
                    artist = excluded.artist,
                    album = excluded.album,
                    duration_ms = excluded.duration_ms,
                    track_id = COALESCE(excluded.track_id, tracks.track_id)
                """,
                (
                    str(media.path),
                    mtime_ns,
                    media.size_bytes,
                    media.title,
                    media.artist,
                    media.album,
                    media.duration_ms,
                    media.track_id,
                ),
            )
            self._connection.commit()

    def set_track_id(self, path: Path, track_id: str) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE tracks SET track_id = ? WHERE path = ?",
                (track_id, str(path)),
            )
            self._connection.commit()

    def find_path_by_track_id(self, track_id: str) -> Path | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT path FROM tracks WHERE track_id = ? LIMIT 1",
                (track_id,),
            ).fetchone()
        return Path(row["path"]) if row else None

    def close(self) -> None:
        with self._lock:
            self._connection.close()

