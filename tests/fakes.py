from pathlib import Path


class FakePlayerBackend:
    def __init__(self) -> None:
        self.path: Path | None = None
        self.playing = False
        self.position = 0
        self.rate = 1.0

    def open(self, path: Path) -> int:
        self.path = path
        self.position = 0
        return 5_000

    def play(self) -> None:
        self.playing = True

    def pause(self) -> None:
        self.playing = False

    def seek_ms(self, position_ms: int) -> None:
        self.position = int(position_ms)

    def position_ms(self) -> int:
        return self.position

    def is_playing(self) -> bool:
        return self.playing

    def set_rate(self, rate: float) -> None:
        self.rate = rate

    def set_volume(self, volume: int) -> None:
        self.volume = volume

    def stop(self) -> None:
        self.playing = False
        self.position = 0

    def close(self) -> None:
        self.stop()

