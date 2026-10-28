import hashlib
import re
from pathlib import Path

import mutagen

from listen_together.library.models import MediaFile
from listen_together.player.vlc_backend import probe_media_duration


_LRC_TIMESTAMP = re.compile(r"^\s*\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]\s*")
_LRC_METADATA = re.compile(
    r"^\s*\[(?:ar|ti|al|by|offset|re|ve|length):.*\]\s*$",
    re.IGNORECASE,
)


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
    lyrics, lyrics_lrc = _read_lyrics(resolved_path, tags)
    return MediaFile(
        path=resolved_path,
        title=title.strip(),
        artist=artist.strip(),
        album=album.strip(),
        duration_ms=duration_ms,
        size_bytes=resolved_path.stat().st_size,
        lyrics=lyrics,
        lyrics_lrc=lyrics_lrc,
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


def _read_lyrics(path: Path, tags) -> tuple[str, str]:
    sidecar = path.with_suffix(".lrc")
    if sidecar.is_file():
        raw = sidecar.read_bytes()
        for encoding in ("utf-8-sig", "gb18030", "utf-16"):
            try:
                decoded = raw.decode(encoding)
                return _clean_lyrics(decoded), decoded[:20_000]
            except UnicodeDecodeError:
                continue

    candidates: list[str] = []
    for key in ("lyrics", "unsyncedlyrics", "LYRICS", "UNSYNCEDLYRICS", "\xa9lyr"):
        try:
            value = tags.get(key)
        except (AttributeError, KeyError):
            continue
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            candidates.extend(_lyric_text(item) for item in value if item)
        else:
            candidates.append(_lyric_text(value))

    try:
        for frame in tags.getall("USLT"):
            candidates.append(str(frame.text))
    except (AttributeError, KeyError):
        pass

    for value in candidates:
        raw_lyrics = _lyric_text(value)
        lyrics = _clean_lyrics(raw_lyrics)
        if lyrics:
            return lyrics, raw_lyrics[:20_000]
    return "", ""


def _lyric_text(value) -> str:
    if isinstance(value, bytes):
        for encoding in ("utf-8", "gb18030", "utf-16"):
            try:
                return value.decode(encoding)
            except UnicodeDecodeError:
                continue
        return value.decode("utf-8", errors="replace")
    return str(value)


def _clean_lyrics(value: str) -> str:
    lines: list[str] = []
    for raw_line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if _LRC_METADATA.match(raw_line):
            continue
        line = raw_line
        while _LRC_TIMESTAMP.match(line):
            line = _LRC_TIMESTAMP.sub("", line, count=1)
        lines.append(line.strip())
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned[:10_000]

