import hashlib
import os
import shutil
import threading
import uuid
from pathlib import Path

from listen_together.library.scanner import compute_sha256


class CacheFullError(RuntimeError):
    pass


class SessionCache:
    def __init__(
        self,
        root: Path,
        *,
        max_bytes: int = 2 * 1024 * 1024 * 1024,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self._lock = threading.RLock()
        self._session_dir = self.root / f"session-{uuid.uuid4().hex}"
        self._session_dir.mkdir(parents=True, exist_ok=False)
        self._remove_stale_sessions()

    @property
    def session_dir(self) -> Path:
        return self._session_dir

    def track_path(self, track_id: str) -> Path:
        digest = hashlib.sha256(track_id.encode("utf-8")).hexdigest()
        return self._session_dir / f"{digest}.media"

    def part_path(self, track_id: str) -> Path:
        digest = hashlib.sha256(track_id.encode("utf-8")).hexdigest()
        return self._session_dir / f"{digest}.part"

    def has_track(self, track_id: str) -> bool:
        return self.track_path(track_id).is_file()

    def ensure_capacity(self, additional_bytes: int) -> None:
        with self._lock:
            self._ensure_capacity(additional_bytes)

    def import_file(
        self,
        source: Path,
        *,
        track_id: str,
        expected_hash: str,
    ) -> Path:
        source_path = Path(source).resolve()
        size = source_path.stat().st_size
        self._ensure_capacity(size)
        destination = self.track_path(track_id)
        part = self.part_path(track_id)
        if destination.is_file():
            return destination
        try:
            shutil.copyfile(source_path, part)
            return self.finalize_part(
                part,
                track_id=track_id,
                expected_hash=expected_hash,
                expected_size=size,
            )
        finally:
            part.unlink(missing_ok=True)

    def finalize_part(
        self,
        part: Path,
        *,
        track_id: str,
        expected_hash: str,
        expected_size: int,
    ) -> Path:
        part = Path(part)
        with self._lock:
            try:
                if part.stat().st_size != expected_size:
                    raise ValueError("Transferred file size does not match.")
                if compute_sha256(part) != expected_hash:
                    raise ValueError("Transferred file failed integrity validation.")
                destination = self.track_path(track_id)
                os.replace(part, destination)
                return destination
            except Exception:
                part.unlink(missing_ok=True)
                raise

    def prune(self, *, keep_track_ids: set[str]) -> None:
        keep_paths = {self.track_path(track_id) for track_id in keep_track_ids}
        with self._lock:
            for path in self._session_dir.iterdir():
                if not path.is_file():
                    continue
                if path.suffix == ".part":
                    keep = path.with_suffix(".media") in keep_paths
                else:
                    keep = path in keep_paths
                if not keep:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass

    def total_bytes(self) -> int:
        total = 0
        for path in self._session_dir.iterdir():
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
        return total

    def clear(self) -> None:
        with self._lock:
            shutil.rmtree(self._session_dir, ignore_errors=True)

    def _ensure_capacity(self, additional_bytes: int) -> None:
        if additional_bytes > self.max_bytes:
            raise CacheFullError("The media file exceeds the session cache limit.")
        if self.total_bytes() + additional_bytes > self.max_bytes:
            raise CacheFullError("The session cache limit has been reached.")

    def _remove_stale_sessions(self) -> None:
        for directory in self.root.glob("session-*"):
            if directory == self._session_dir or not directory.is_dir():
                continue
            try:
                shutil.rmtree(directory)
            except OSError:
                continue
