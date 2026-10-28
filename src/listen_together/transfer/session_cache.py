import hashlib
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from listen_together.library.scanner import compute_sha256


class CacheFullError(RuntimeError):
    pass


class SessionCache:
    DEFAULT_MAX_BYTES = 1024 * 1024 * 1024

    def __init__(self, root: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self._lock = threading.RLock()
        self._session_dir = self.root / f"session-{uuid.uuid4().hex}"
        self._session_dir.mkdir(parents=True, exist_ok=False)
        self._pinned_track_ids: set[str] = set()
        self._reservations: dict[str, int] = {}
        self._last_access_ns: dict[Path, int] = {}
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
        path = self.track_path(track_id)
        with self._lock:
            exists = path.is_file()
            if exists:
                self._touch(path)
            return exists

    def set_pinned_track_ids(self, track_ids: set[str]) -> None:
        with self._lock:
            self._pinned_track_ids = {str(track_id) for track_id in track_ids}

    def reserve(self, track_id: str, size_bytes: int) -> None:
        with self._lock:
            destination = self.track_path(track_id)
            if destination.is_file():
                return
            reserved = self._reservations.get(track_id)
            if reserved is not None and reserved >= size_bytes:
                return
            self._reservations.pop(track_id, None)
            self.part_path(track_id).unlink(missing_ok=True)
            self._ensure_capacity(size_bytes, track_id=track_id)
            self._reservations[track_id] = size_bytes

    def release_reservation(self, track_id: str) -> None:
        with self._lock:
            self._reservations.pop(track_id, None)

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
        destination = self.track_path(track_id)
        if destination.is_file():
            with self._lock:
                self._touch(destination)
            return destination
        part = self.part_path(track_id)
        self.reserve(track_id, size)
        try:
            shutil.copyfile(source_path, part)
            return self.finalize_part(
                part,
                track_id=track_id,
                expected_hash=expected_hash,
                expected_size=size,
            )
        finally:
            self.release_reservation(track_id)
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
                self._touch(destination)
                return destination
            except Exception:
                part.unlink(missing_ok=True)
                raise
            finally:
                self._reservations.pop(track_id, None)

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
                    self._last_access_ns.pop(path, None)

    def prune_to_limit(self) -> None:
        with self._lock:
            while self.total_bytes() > self.max_bytes:
                victim = self._oldest_evictable()
                if victim is None:
                    return
                try:
                    victim.unlink(missing_ok=True)
                except OSError:
                    return
                self._last_access_ns.pop(victim, None)

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
            self._reservations.clear()
            self._pinned_track_ids.clear()
            self._last_access_ns.clear()
            shutil.rmtree(self._session_dir, ignore_errors=True)

    def _ensure_capacity(self, additional_bytes: int, *, track_id: str | None = None) -> None:
        self._remove_unreserved_parts()
        if additional_bytes > self.max_bytes:
            raise CacheFullError(
                f"歌曲需要 {additional_bytes / (1024 * 1024):.1f} MB，"
                f"超过当前缓存上限 {self.max_bytes / (1024 * 1024):.0f} MB。"
            )
        reserved = sum(
            reserved_bytes
            for reserved_id, reserved_bytes in self._reservations.items()
            if reserved_id != track_id
        )
        while self.total_bytes() + reserved + additional_bytes > self.max_bytes:
            victim = self._oldest_evictable()
            if victim is None:
                break
            try:
                victim.unlink(missing_ok=True)
            except OSError:
                break
            self._last_access_ns.pop(victim, None)
        if self.total_bytes() + reserved + additional_bytes > self.max_bytes:
            raise CacheFullError(
                "缓存空间不足：当前歌曲和下一首需要更多空间，"
                "请关闭其他程序或等待当前歌曲播放结束。"
            )

    def _remove_unreserved_parts(self) -> None:
        reserved_parts = {
            self.part_path(track_id) for track_id in self._reservations
        }
        for part in self._session_dir.glob("*.part"):
            if part in reserved_parts:
                continue
            try:
                part.unlink(missing_ok=True)
            except OSError:
                pass

    def _oldest_evictable(self) -> Path | None:
        reserved_paths = {
            self.track_path(track_id) for track_id in self._reservations
        }
        pinned_paths = {
            self.track_path(track_id) for track_id in self._pinned_track_ids
        }
        candidates: list[tuple[int, Path]] = []
        for path in self._session_dir.glob("*.media"):
            if path in reserved_paths or path in pinned_paths:
                continue
            try:
                accessed = self._last_access_ns.get(path, path.stat().st_mtime_ns)
            except OSError:
                continue
            candidates.append((accessed, path))
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[0])[1]

    def _touch(self, path: Path) -> None:
        self._last_access_ns[path] = time.monotonic_ns()

    def _remove_stale_sessions(self) -> None:
        for directory in self.root.glob("session-*"):
            if directory == self._session_dir or not directory.is_dir():
                continue
            try:
                shutil.rmtree(directory)
            except OSError:
                continue
