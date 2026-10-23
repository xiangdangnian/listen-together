import os
import struct
import tempfile
import time
import unittest
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from listen_together.app_controller import AppController
from listen_together.ui.main_window import MainWindow
from tests.fakes import FakePlayerBackend


def write_tone(path: Path) -> None:
    sample_rate = 8_000
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(struct.pack("<h", 0) * sample_rate)


class MainWindowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_window_renders_with_local_queue(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        music_dir = root / "music"
        music_dir.mkdir()
        write_tone(music_dir / "测试歌曲.wav")
        controller = AppController(
            data_dir=root / "data",
            backend_factory=FakePlayerBackend,
        )
        settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
        window = MainWindow(controller, settings=settings)
        try:
            window.resize(1280, 800)
            window.show()
            self.app.processEvents()
            tracks = controller.library.scan_directory(music_dir)
            window._refresh_library()
            controller.add_track(tracks[0])

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                controller.tick()
                self.app.processEvents()
                if controller.snapshot.get("queue"):
                    break
                time.sleep(0.02)
            self.app.processEvents()
            window._render_snapshot()
            self.app.processEvents()

            image = window.grab()
            self.assertGreaterEqual(image.width(), 1100)
            self.assertGreaterEqual(image.height(), 720)
            output = Path(__file__).parents[1] / "docs" / "ui-preview.png"
            self.assertTrue(image.save(str(output), "PNG"))
            self.assertGreater(output.stat().st_size, 10_000)
        finally:
            window.close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
