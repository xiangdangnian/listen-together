import os
import struct
import tempfile
import time
import unittest
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QAbstractItemView, QApplication, QSplitter

from listen_together.app_controller import AppController
from listen_together.ui.main_window import MainWindow
from tests.fakes import FakePlayerBackend


def write_tone(path: Path, *, duration_ms: int = 1_000) -> None:
    sample_rate = 8_000
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(struct.pack("<h", 0) * (sample_rate * duration_ms // 1_000))


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
        song_path = music_dir / "测试歌曲.wav"
        write_tone(song_path, duration_ms=60_000)
        song_path.with_suffix(".lrc").write_text(
            "[00:01.00]第一行歌词\n[00:02.00]第二行歌词\n",
            encoding="utf-8",
        )
        write_tone(music_dir / "第二首.wav", duration_ms=62_000)
        controller = AppController(
            data_dir=root / "data",
            backend_factory=FakePlayerBackend,
        )
        settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
        settings.setValue("display_name", "测试用户")
        window = MainWindow(controller, settings=settings)
        try:
            window.resize(1280, 800)
            window.show()
            self.app.processEvents()
            tracks = controller.library.scan_directory(music_dir)
            window._refresh_library()
            test_track = next(
                track for track in tracks if track.path.name == "测试歌曲.wav"
            )
            controller.add_track(test_track)

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
            self.assertEqual(window.members_label.text(), "测试用户")
            self.assertEqual(
                window.library_list.selectionMode(),
                QAbstractItemView.SelectionMode.ExtendedSelection,
            )
            self.assertEqual(
                window.queue_list.selectionMode(),
                QAbstractItemView.SelectionMode.ExtendedSelection,
            )
            window.library_list.selectAll()
            self.app.processEvents()
            self.assertTrue(window.add_selected_button.isEnabled())
            self.assertIsInstance(window.content_splitter, QSplitter)
            self.assertTrue(window.listening_time_label.text().startswith("听歌 "))
            window.content_splitter.setSizes([260, 720, 300])
            self.app.processEvents()
            window._remember_splitter_sizes()
            window._toggle_left_panel()
            self.assertTrue(window.left_panel.isHidden())
            window._toggle_left_panel()
            self.assertFalse(window.left_panel.isHidden())
            window._toggle_right_panel()
            self.assertTrue(window.right_panel.isHidden())
            window._toggle_right_panel()
            self.assertFalse(window.right_panel.isHidden())
            self.assertIn("第一行歌词", window.lyrics_view.toPlainText())
            self.assertFalse(window.lyrics_view.isHidden())
            window._update_lyrics_position(1_500)
            self.assertEqual(window._lyric_index, 0)
            window._update_lyrics_position(2_500)
            self.app.processEvents()
            self.assertEqual(window._lyric_index, 1)
            block = window.lyrics_view.document().findBlockByNumber(1)
            cursor = QTextCursor(block)
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            self.assertEqual(cursor.charFormat().fontPointSize(), 20)
            self.assertTrue(
                block.blockFormat().alignment() & Qt.AlignmentFlag.AlignHCenter
            )
            block_layout = block.layout()
            rendered_center = (
                block_layout.position().y()
                + block_layout.lineAt(0).naturalTextRect().center().y()
                - window.lyrics_view.verticalScrollBar().value()
            )
            self.assertLessEqual(
                abs(rendered_center - window.lyrics_view.viewport().height() // 2),
                6,
            )
            window._update_lyrics_position(1_500)
            self.app.processEvents()
            self.assertEqual(window._lyric_index, 0)
            window._update_lyrics_position(2_500)
            self.app.processEvents()
            window.queue_list.setCurrentRow(0)
            self.app.processEvents()
            self.assertTrue(window.delete_queue_button.isEnabled())
            window._apply_appearance_preset("dark", 100)
            self.app.processEvents()
            self.assertIn("#1B1D21", window.styleSheet())
            self.assertAlmostEqual(window.windowOpacity(), 1.0, places=1)
            dark_output = Path(__file__).parents[1] / "docs" / "theme-dark-preview.png"
            self.assertTrue(window.grab().save(str(dark_output), "PNG"))
            window._apply_appearance_preset("cool-acrylic", 80)
            self.app.processEvents()
            self.assertIn("rgba", window.styleSheet())
            self.assertGreaterEqual(window.windowOpacity(), 0.84)
            glass_output = Path(__file__).parents[1] / "docs" / "theme-glass-preview.png"
            self.assertTrue(window.grab().save(str(glass_output), "PNG"))
            window._apply_appearance_preset("glass", 80)
            self.app.processEvents()
            self.assertAlmostEqual(window.windowOpacity(), 0.8, places=1)
            window._apply_appearance_preset("light", 100)
            self.app.processEvents()

            window._update_lyrics_position(2_500)
            self.app.processEvents()
            image = window.grab()
            self.assertGreaterEqual(image.width(), 1100)
            self.assertGreaterEqual(image.height(), 720)
            output = Path(__file__).parents[1] / "docs" / "ui-preview.png"
            self.assertTrue(image.save(str(output), "PNG"))
            self.assertGreater(output.stat().st_size, 10_000)

            window.library_list.selectAll()
            window._add_selected_library_tracks()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                controller.tick()
                self.app.processEvents()
                if len(controller.snapshot.get("queue", [])) >= 3:
                    break
                time.sleep(0.02)
            window.queue_list.selectAll()
            self.app.processEvents()
            self.assertTrue(window.delete_queue_button.isEnabled())
            window._remove_selected_queue_item()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                controller.tick()
                self.app.processEvents()
                if not controller.snapshot.get("queue"):
                    break
                time.sleep(0.02)
            self.assertEqual(controller.snapshot.get("queue"), [])
        finally:
            window.close()
            self.app.processEvents()


    def test_locate_current_track_and_mode_button_position(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        controller = AppController(
            data_dir=root / "data",
            backend_factory=FakePlayerBackend,
        )
        window = MainWindow(
            controller,
            settings=QSettings(
                str(root / "settings.ini"),
                QSettings.Format.IniFormat,
            ),
        )
        try:
            window.resize(1280, 800)
            window.show()
            self.app.processEvents()
            queue = [
                {
                    "queue_id": f"queue_{index}",
                    "track_id": f"sha256:{index:064x}",
                    "source_member_id": "host",
                    "added_by": "host",
                    "title": f"歌曲 {index}",
                    "artist": "歌手",
                    "duration_ms": 180_000,
                    "size_bytes": 1_000,
                }
                for index in range(40)
            ]
            controller.snapshot = {
                "queue": queue,
                "current_index": 30,
                "members": [],
                "playback": {},
                "queue_revision": 1,
            }
            window._rebuild_queue(queue, 30)
            window.queue_list.scrollToTop()
            self.app.processEvents()
            item = window.queue_list.item(30)
            self.assertIsNotNone(item)
            self.assertFalse(
                window.queue_list.viewport().rect().intersects(
                    window.queue_list.visualItemRect(item)
                )
            )

            window.locate_button.setEnabled(True)
            window._locate_current_track()
            self.app.processEvents()

            self.assertTrue(
                window.queue_list.viewport().rect().intersects(
                    window.queue_list.visualItemRect(item)
                )
            )
            slider_pos = window.volume_slider.mapTo(window, QPoint(0, 0))
            mode_pos = window.mode_button.mapTo(window, QPoint(0, 0))
            self.assertGreater(mode_pos.x(), slider_pos.x() + window.volume_slider.width())
        finally:
            window.close()
            self.app.processEvents()

    def test_client_delete_button_only_allows_own_tracks(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        controller = AppController(
            data_dir=root / "data",
            backend_factory=FakePlayerBackend,
        )
        window = MainWindow(
            controller,
            settings=QSettings(
                str(root / "settings.ini"),
                QSettings.Format.IniFormat,
            ),
        )
        try:
            controller.role = "client"
            controller.member_id = "guest"
            queue = [
                {
                    "queue_id": "queue_host",
                    "track_id": "sha256:1",
                    "source_member_id": "host",
                    "added_by": "host",
                    "title": "Host song",
                    "artist": "Artist",
                    "duration_ms": 1_000,
                    "size_bytes": 100,
                },
                {
                    "queue_id": "queue_guest",
                    "track_id": "sha256:2",
                    "source_member_id": "guest",
                    "added_by": "guest",
                    "title": "Guest song",
                    "artist": "Artist",
                    "duration_ms": 1_000,
                    "size_bytes": 100,
                },
            ]
            controller.snapshot = {
                "queue": queue,
                "current_index": 0,
                "members": [],
                "playback": {},
                "queue_revision": 1,
            }
            window._rebuild_queue(queue, 0)
            window.queue_list.setCurrentRow(0)
            self.app.processEvents()
            self.assertFalse(window.delete_queue_button.isEnabled())

            window.queue_list.setCurrentRow(1)
            self.app.processEvents()
            self.assertTrue(window.delete_queue_button.isEnabled())
        finally:
            window.close()
            self.app.processEvents()
if __name__ == "__main__":
    unittest.main()
