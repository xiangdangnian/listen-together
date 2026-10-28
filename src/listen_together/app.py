import math
import os
import struct
import sys
import tempfile
import time
import traceback
import wave
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from listen_together.app_controller import AppController
from listen_together.player.vlc_backend import VLCBackend
from listen_together.ui.main_window import MainWindow


INSTANCE_KEY = "listen-together-single-instance"


def _activate_existing_instance() -> bool:
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_KEY)
    if not socket.waitForConnected(300):
        return False
    socket.write(b"activate")
    socket.waitForBytesWritten(300)
    socket.disconnectFromServer()
    return True


def main() -> int:
    if "--audio-self-test" in sys.argv:
        return _run_audio_self_test()

    QApplication.setOrganizationName("ListenTogether")
    QApplication.setApplicationName("ListenTogether")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    icon_path = _resource_path("listen_together/assets/app-icon.png")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    if "--smoke-test" in sys.argv:
        return _run_smoke_test(app)

    if _activate_existing_instance():
        return 0

    QLocalServer.removeServer(INSTANCE_KEY)
    instance_server = QLocalServer()
    if not instance_server.listen(INSTANCE_KEY):
        raise RuntimeError("Could not create the single-instance lock.")

    data_location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    data_dir = Path(data_location or Path.home() / "ListenTogether")
    controller = AppController(data_dir=data_dir)
    window = MainWindow(controller)

    def activate_existing() -> None:
        while instance_server.hasPendingConnections():
            connection = instance_server.nextPendingConnection()
            connection.readAll()
            connection.disconnectFromServer()
        window.showNormal()
        window.raise_()
        window.activateWindow()

    instance_server.newConnection.connect(activate_existing)
    window.show()
    return app.exec()


def _resource_path(relative_path: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / relative_path
    return Path(__file__).resolve().parent.parent.parent / "src" / relative_path


def _run_audio_self_test() -> int:
    log_path = Path(
        os.environ.get(
            "LISTEN_TOGETHER_SELF_TEST_LOG",
            Path.cwd() / "audio-self-test.log",
        )
    )
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "tone.wav"
            sample_rate = 8_000
            with wave.open(str(audio_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(sample_rate)
                frames = bytearray()
                for index in range(sample_rate * 2):
                    value = int(
                        8_000
                        * math.sin(2 * math.pi * 440 * index / sample_rate)
                    )
                    frames.extend(struct.pack("<h", value))
                audio.writeframes(bytes(frames))

            backend = VLCBackend(audio_output="dummy")
            try:
                duration_ms = backend.open(audio_path)
                backend.play()
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline and backend.position_ms() < 100:
                    time.sleep(0.02)
                if backend.position_ms() < 100:
                    raise RuntimeError("VLC did not advance during the audio test.")
                backend.pause()
                backend.seek_ms(500)
            finally:
                backend.close()
        log_path.write_text(f"OK duration_ms={duration_ms}\n", encoding="utf-8")
        return 0
    except Exception:
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        return 1


def _run_smoke_test(app: QApplication) -> int:
    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    output = Path(os.environ.get("LISTEN_TOGETHER_SMOKE_PATH", "ui-smoke.png"))
    controller = AppController(data_dir=root / "data")
    settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(controller, settings=settings)
    window.resize(1280, 800)
    window.show()

    def capture_and_exit() -> None:
        app.processEvents()
        window.grab().save(str(output), "PNG")
        window.close()
        app.quit()

    QTimer.singleShot(900, capture_and_exit)
    result = app.exec()
    temp_dir.cleanup()
    return result


if __name__ == "__main__":
    raise SystemExit(main())

