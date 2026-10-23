from pathlib import Path

from listen_together.player.base import PlaybackState, PlayerBackend


class PlaybackController:
    def __init__(self, backend: PlayerBackend) -> None:
        self._backend = backend
        self._state = PlaybackState.IDLE
        self._duration_ms = 0
        self._has_media = False
        self._volume = 80

    @property
    def state(self) -> PlaybackState:
        return self._state

    @property
    def duration_ms(self) -> int:
        return self._duration_ms

    @property
    def volume(self) -> int:
        return self._volume

    def load(self, path: Path) -> None:
        try:
            if self._has_media:
                self._backend.stop()
            self._duration_ms = max(0, self._backend.open(path))
            self._backend.set_volume(self._volume)
            self._has_media = True
            self._state = PlaybackState.READY
        except Exception:
            self._state = PlaybackState.ERROR
            raise

    def play(self) -> None:
        self._require_media()
        if self._state is PlaybackState.PLAYING:
            return
        try:
            self._backend.play()
            self._state = PlaybackState.PLAYING
        except Exception:
            self._state = PlaybackState.ERROR
            raise

    def pause(self) -> None:
        self._require_media()
        if self._state is not PlaybackState.PLAYING:
            return
        try:
            self._backend.pause()
            self._state = PlaybackState.PAUSED
        except Exception:
            self._state = PlaybackState.ERROR
            raise

    def seek_ms(self, position_ms: int) -> int:
        self._require_media()
        target_ms = min(max(0, position_ms), self._duration_ms)
        try:
            self._backend.seek_ms(target_ms)
        except Exception:
            self._state = PlaybackState.ERROR
            raise
        return target_ms

    def position_ms(self) -> int:
        self._require_media()
        return min(max(0, self._backend.position_ms()), self._duration_ms)

    def set_rate(self, rate: float) -> None:
        self._require_media()
        if rate <= 0:
            raise ValueError("Playback rate must be positive.")
        self._backend.set_rate(rate)

    def set_volume(self, volume: int) -> None:
        self._volume = min(max(0, int(volume)), 100)
        if self._has_media:
            self._backend.set_volume(self._volume)

    def stop(self) -> None:
        if not self._has_media:
            return
        self._backend.stop()
        self._state = PlaybackState.STOPPED

    def close(self) -> None:
        self._backend.close()
        self._has_media = False
        self._duration_ms = 0
        self._state = PlaybackState.IDLE

    def _require_media(self) -> None:
        if not self._has_media:
            raise RuntimeError("No media has been loaded.")
