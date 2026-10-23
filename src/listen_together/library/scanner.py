import hashlib
from pathlib import Path

import mutagen

from listen_together.library.models import MediaFile
from listen_together.player.vlc_backend import probe_media_duration


SUPPORTED_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".m4a",
    ".mp4",
    ".wav",
    ".ogg",
    ".opus",
    ".aac",
    ".ape",
}


def iter_audio_paths(directory: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ),
        key=lambda path: path.name.casefold(),
    )


def read_media_file(path: Path) -> MediaFile:
    resolved_path = path.resolve()
    audio = mutagen.File(resolved_path)
    if audio is None or audio.info is None:
        raise ValueError(f"Unsupported or unreadable audio file: {path}")

    tags = audio.tags or {}
    title = _tag_value(tags, ("title", "TIT2", "\xa9nam")) or resolved_path.stem
    artist = _tag_value(tags, ("artist", "TPE1", "\xa9ART")) or ""
    album = _tag_value(tags, ("album", "TALB", "\xa9alb")) or ""
    duration_ms = max(1, round(float(audio.info.length) * 1000))
    if duration_ms <= 100:
        try:
            duration_ms = probe_media_duration(resolved_path)
        except Exception:
            duration_ms = max(1, duration_ms)
    return MediaFile(
        path=resolved_path,
        title=title.strip(),
        artist=artist.strip(),
        album=album.strip(),
        duration_ms=duration_ms,
        size_bytes=resolved_path.stat().st_size,
    )


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _tag_value(tags, keys: tuple[str, ...]) -> str:
    for key in keys:
        try:
            value = tags.get(key)
        except (AttributeError, KeyError):
            continue
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        return str(value)
    return ""

