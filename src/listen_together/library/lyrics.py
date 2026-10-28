import re
from bisect import bisect_right
from dataclasses import dataclass


_TIMESTAMP = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")


@dataclass(frozen=True, slots=True)
class LyricLine:
    time_ms: int
    text: str


def parse_lrc(value: str) -> list[LyricLine]:
    parsed: list[LyricLine] = []
    for raw_line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        matches = list(_TIMESTAMP.finditer(raw_line))
        if not matches:
            continue
        text = _TIMESTAMP.sub("", raw_line).strip()
        if not text:
            continue
        for match in matches:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            fraction = match.group(3) or "0"
            milliseconds = int(fraction.ljust(3, "0")[:3])
            parsed.append(
                LyricLine(
                    time_ms=minutes * 60_000 + seconds * 1_000 + milliseconds,
                    text=text,
                )
            )
    parsed.sort(key=lambda line: line.time_ms)
    return parsed


def timed_lyric_index(lines: list[LyricLine], position_ms: int) -> int:
    if not lines:
        return -1
    return bisect_right(
        [line.time_ms for line in lines],
        max(0, position_ms),
    ) - 1
