import os
import sys
import time
from pathlib import Path


def _load_vlc_module():
    if sys.platform == "win32":
        candidates = []
        if getattr(sys, "frozen", False):
            candidates.extend(
                [
                    Path(sys.executable).resolve().parent / "vlc",
                    Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
                    / "vlc",
                ]
            )
        candidates.extend([
            Path(os.environ["VLC_HOME"]) if "VLC_HOME" in os.environ else None,
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "VideoLAN"
            / "VLC",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "VideoLAN"
            / "VLC",
        ])
        for directory in candidates:
            if directory is None:
                continue
            library = directory / "libvlc.dll"
            if library.exists():
                os.add_dll_directory(str(directory))
                os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(library))
                plugins = directory / "plugins"
                if plugins.is_dir():
                    os.environ.setdefault("VLC_PLUGIN_PATH", str(plugins))
                break

    try:
        import vlc
    except ImportError as error:
        raise RuntimeError(
            "python-vlc is unavailable. Install the project dependencies first."
        ) from error
    return vlc


vlc = _load_vlc_module()


class VLCBackend:
    def __init__(self, *, audio_output: str | None = None) -> None:
        arguments = ["--no-video", "--quiet"]
        if audio_output:
            arguments.append(f"--aout={audio_output}")

        self._instance = vlc.Instance(*arguments)
        if self._instance is None:
            raise RuntimeError("Could not create the VLC instance.")

        self._player = self._instance.media_player_new()
        if self._player is None:
            self._instance.release()
            raise RuntimeError("Could not create the VLC media player.")

        self._media = None
        self._closed = False

    def open(self, path: Path) -> int:
        self._ensure_open()
        media_path = Path(path).resolve()
        if not media_path.is_file():
            raise FileNotFoundError(media_path)

        self.stop()
        media = self._instance.media_new(str(media_path))
        media.parse()
        duration_ms = media.get_duration()
        self._player.set_media(media)
        self._media = media
        if duration_ms <= 0:
            previous_volume = self._player.audio_get_volume()
            if previous_volume < 0:
                previous_volume = 100
            self._player.audio_set_volume(0)
            try:
                self._player.play()
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline:
                    duration_ms = self._player.get_length()
                    if duration_ms > 0:
                        break
                    if self._player.get_state() in (
                        vlc.State.Error,
                        vlc.State.Ended,
                        vlc.State.Stopped,
                    ):
                        break
                    time.sleep(0.03)
            finally:
                self._player.stop()
                self._player.audio_set_volume(previous_volume)

        if duration_ms <= 0:
            media.release()
            self._media = None
            raise RuntimeError(f"Could not read media duration: {media_path.name}")

        return duration_ms

    def play(self) -> None:
        self._ensure_open()
        if self._player.play() == -1:
            raise RuntimeError("VLC could not start playback.")

    def pause(self) -> None:
        self._ensure_open()
        if self._player.is_playing():
            self._player.pause()

    def seek_ms(self, position_ms: int) -> None:
        self._ensure_open()
        if self._player.set_time(max(0, int(position_ms))) == -1:
            raise RuntimeError("VLC could not seek.")

    def position_ms(self) -> int:
        self._ensure_open()
        return max(0, self._player.get_time())

    def is_playing(self) -> bool:
        self._ensure_open()
        return bool(self._player.is_playing())

    def set_rate(self, rate: float) -> None:
        self._ensure_open()
        if rate <= 0:
            raise ValueError("Playback rate must be positive.")
        self._player.set_rate(rate)
        if abs(self._player.get_rate() - rate) > 0.01:
            raise RuntimeError("VLC did not apply the requested playback rate.")

    def set_volume(self, volume: int) -> None:
        self._ensure_open()
        self._player.audio_set_volume(min(max(0, int(volume)), 100))

    def stop(self) -> None:
        self._ensure_open()
        self._player.stop()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._player.stop()
        self._player.release()
        if self._media is not None:
            self._media.release()
            self._media = None
        self._instance.release()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("VLC backend is closed.")


def probe_media_duration(path: Path) -> int:
    backend = VLCBackend(audio_output="dummy")
    try:
        return backend.open(path)
    finally:
        backend.close()
