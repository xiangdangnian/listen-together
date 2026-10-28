import math
import struct
import tempfile
import time
import wave
from pathlib import Path

from listen_together.app_controller import AppController
from listen_together.player.vlc_backend import VLCBackend


class RecordingVLCBackend(VLCBackend):
    def __init__(self) -> None:
        super().__init__(audio_output="dummy")
        self.seek_count = 0
        self.seek_positions: list[int] = []

    def seek_ms(self, position_ms: int) -> None:
        self.seek_count += 1
        self.seek_positions.append(int(position_ms))
        super().seek_ms(position_ms)


def write_tone(path: Path, duration_s: int) -> None:
    sample_rate = 8_000
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        frames = bytearray()
        for index in range(sample_rate * duration_s):
            value = int(8_000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(struct.pack("<h", value))
        audio.writeframes(bytes(frames))


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        music = root / "music"
        music.mkdir()
        write_tone(music / "trace.wav", 8)
        backends: list[RecordingVLCBackend] = []

        def make_backend() -> RecordingVLCBackend:
            backend = RecordingVLCBackend()
            backends.append(backend)
            return backend

        controller = AppController(
            data_dir=root / "data",
            backend_factory=make_backend,
        )
        try:
            tracks = controller.library.scan_directory(music)
            controller.add_track(tracks[0])
            deadline = time.monotonic() + 8
            next_report = 0.0
            while time.monotonic() < deadline:
                controller.tick()
                now = time.monotonic()
                if now >= next_report:
                    backend = backends[0] if backends else None
                    target = controller.current_position_ms()
                    actual = backend.position_ms() if backend else 0
                    seeks = backend.seek_count if backend else 0
                    print(
                        "playing",
                        controller.snapshot.get("playback", {}).get("playing"),
                        "target",
                        target,
                        "actual",
                        actual,
                        "drift",
                        actual - target,
                        "seeks",
                        seeks,
                    )
                    next_report = now + 0.5
                time.sleep(0.05)
            backend = backends[0] if backends else None
            print("total_seeks", backend.seek_count if backend else 0)
            print("seek_positions", backend.seek_positions if backend else [])
        finally:
            controller.close()


if __name__ == "__main__":
    main()
