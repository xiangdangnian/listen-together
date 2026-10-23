import json
import os
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from listen_together.app_controller import AppController
from listen_together.library.models import MediaFile
from listen_together.ui.dialogs import CreateRoomDialog, JoinRoomDialog
from listen_together.ui.theme import APP_STYLE


def _format_time(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"


class QueueListWidget(QListWidget):
    reorder_requested = Signal(str, object)
    remove_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def dropEvent(self, event) -> None:
        item = self.currentItem()
        if item is None:
            return
        queue_id = item.data(Qt.ItemDataRole.UserRole)
        super().dropEvent(event)
        row = self.row(item)
        next_item = self.item(row + 1)
        before_queue_id = (
            next_item.data(Qt.ItemDataRole.UserRole) if next_item is not None else None
        )
        self.reorder_requested.emit(str(queue_id), before_queue_id)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            item = self.currentItem()
            if item is not None:
                self.remove_requested.emit(str(item.data(Qt.ItemDataRole.UserRole)))
                return
        super().keyPressEvent(event)

    def _show_context_menu(self, position) -> None:
        item = self.itemAt(position)
        if item is None:
            return
        menu = QMenu(self)
        action = QAction("从歌单移除", menu)
        action.triggered.connect(
            lambda: self.remove_requested.emit(
                str(item.data(Qt.ItemDataRole.UserRole))
            )
        )
        menu.addAction(action)
        menu.exec(self.mapToGlobal(position))


class MainWindow(QMainWindow):
    def __init__(
        self,
        controller: AppController,
        *,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.settings = settings or QSettings("ListenTogether", "ListenTogether")
        self._last_render_signature = ""
        self._queue_signature = ""
        self._library_signature = ""
        self._slider_dragging = False
        self._display_name = self._initial_display_name()
        self.setWindowTitle("一起听音乐")
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        self.controller.set_event_callback(self._on_controller_event)
        self.controller.start_local_session(self._display_name)
        self._restore_settings()

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        library_folder = self.settings.value("library_folder", "", type=str)
        if library_folder and Path(library_folder).is_dir():
            self._start_library_scan(Path(library_folder))

    def _initial_display_name(self) -> str:
        configured = self.settings.value("display_name", "", type=str)
        if configured:
            return configured
        return os.environ.get("USERNAME", "听众")[:24]

    def _build_ui(self) -> None:
        page = QWidget()
        page.setObjectName("Page")
        self.setCentralWidget(page)
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_top_bar())
        root.addWidget(self._divider())

        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._build_library_panel(), 0)
        content_layout.addWidget(self._divider_vertical())
        content_layout.addWidget(self._build_player_panel(), 1)
        content_layout.addWidget(self._divider_vertical())
        content_layout.addWidget(self._build_queue_panel(), 0)
        root.addWidget(content, 1)
        root.addWidget(self._divider())
        root.addWidget(self._build_event_bar())

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(64)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(12)

        self.room_title = QLabel("本地播放")
        self.room_title.setObjectName("RoomTitle")
        self.online_label = QLabel("1 人在线")
        self.online_label.setObjectName("Secondary")
        self.connection_label = QLabel("本地")
        self.connection_label.setObjectName("Secondary")
        self.address_label = QLabel("")
        self.address_label.setObjectName("Muted")

        text_layout = QVBoxLayout()
        text_layout.setSpacing(1)
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        title_row.addWidget(self.room_title)
        title_row.addWidget(self.online_label)
        title_row.addWidget(self.connection_label)
        title_row.addStretch(1)
        text_layout.addLayout(title_row)
        text_layout.addWidget(self.address_label)
        layout.addLayout(text_layout, 1)

        self.create_button = QPushButton("创建房间")
        self.create_button.setObjectName("Primary")
        self.join_button = QPushButton("加入房间")
        self.copy_button = QPushButton("复制房间信息")
        self.leave_button = QPushButton("退出房间")
        self.leave_button.setObjectName("Danger")
        self.create_button.clicked.connect(self._create_room)
        self.join_button.clicked.connect(self._join_room)
        self.copy_button.clicked.connect(self._copy_room_info)
        self.leave_button.clicked.connect(self._leave_room)
        layout.addWidget(self.create_button)
        layout.addWidget(self.join_button)
        layout.addWidget(self.copy_button)
        layout.addWidget(self.leave_button)
        return bar

    def _build_library_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("Sidebar")
        panel.setFixedWidth(300)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 18, 16, 12)
        layout.setSpacing(10)

        heading = QLabel("本地音乐库")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索歌曲或歌手")
        self.search_input.textChanged.connect(self._refresh_library)
        layout.addWidget(self.search_input)
        self.library_list = QListWidget()
        self.library_list.itemDoubleClicked.connect(self._add_library_item)
        layout.addWidget(self.library_list, 1)
        self.add_folder_button = QPushButton("添加音乐目录")
        self.add_folder_button.clicked.connect(self._choose_music_folder)
        layout.addWidget(self.add_folder_button)
        return panel

    def _build_player_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(40, 28, 40, 24)
        layout.setSpacing(12)

        layout.addStretch(1)
        self.cover_label = QLabel()
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setFixedSize(156, 156)
        self.cover_label.setStyleSheet(
            "background: #F0F4FF; border-radius: 8px; color: #3370FF;"
        )
        self.cover_label.setPixmap(
            self.style()
            .standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
            .pixmap(56, 56)
        )
        layout.addWidget(self.cover_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.track_title = QLabel("还没有播放歌曲")
        self.track_title.setObjectName("TrackTitle")
        self.track_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.track_artist = QLabel("从左侧音乐库双击歌曲加入播放")
        self.track_artist.setObjectName("Secondary")
        self.track_artist.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.requester_label = QLabel("")
        self.requester_label.setObjectName("Muted")
        self.requester_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.track_title)
        layout.addWidget(self.track_artist)
        layout.addWidget(self.requester_label)

        self.status_label = QLabel("选择一首歌开始")
        self.status_label.setObjectName("StatusText")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 0)
        self.progress_slider.sliderPressed.connect(self._slider_pressed)
        self.progress_slider.sliderReleased.connect(self._slider_released)
        layout.addWidget(self.progress_slider)
        time_row = QHBoxLayout()
        self.elapsed_label = QLabel("0:00")
        self.elapsed_label.setObjectName("Muted")
        self.duration_label = QLabel("0:00")
        self.duration_label.setObjectName("Muted")
        time_row.addWidget(self.elapsed_label)
        time_row.addStretch(1)
        time_row.addWidget(self.duration_label)
        layout.addLayout(time_row)

        controls = QHBoxLayout()
        controls.setSpacing(18)
        controls.addStretch(1)
        self.previous_button = self._icon_button(
            QStyle.StandardPixmap.SP_MediaSkipBackward,
            "上一首",
        )
        self.play_button = self._icon_button(
            QStyle.StandardPixmap.SP_MediaPlay,
            "播放或暂停",
        )
        self.play_button.setFixedSize(46, 46)
        self.next_button = self._icon_button(
            QStyle.StandardPixmap.SP_MediaSkipForward,
            "下一首",
        )
        self.previous_button.clicked.connect(self.controller.previous_track)
        self.play_button.clicked.connect(self.controller.play_pause)
        self.next_button.clicked.connect(self.controller.next_track)
        controls.addWidget(self.previous_button)
        controls.addWidget(self.play_button)
        controls.addWidget(self.next_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        volume_row = QHBoxLayout()
        volume_row.addStretch(1)
        volume_icon = QLabel()
        volume_icon.setPixmap(
            self.style()
            .standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
            .pixmap(18, 18)
        )
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedWidth(150)
        self.volume_slider.valueChanged.connect(self.controller.set_volume)
        volume_row.addWidget(volume_icon)
        volume_row.addWidget(self.volume_slider)
        volume_row.addStretch(1)
        layout.addLayout(volume_row)
        layout.addStretch(1)
        return panel

    def _build_queue_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("Sidebar")
        panel.setFixedWidth(340)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 18, 16, 12)
        layout.setSpacing(10)
        heading_row = QHBoxLayout()
        heading = QLabel("共享歌单")
        heading.setObjectName("SectionTitle")
        self.queue_count = QLabel("0 首")
        self.queue_count.setObjectName("Muted")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        heading_row.addWidget(self.queue_count)
        layout.addLayout(heading_row)
        self.queue_list = QueueListWidget()
        self.queue_list.itemDoubleClicked.connect(self._play_queue_item)
        self.queue_list.reorder_requested.connect(self.controller.move_queue_item)
        self.queue_list.remove_requested.connect(self.controller.remove_queue_item)
        layout.addWidget(self.queue_list, 1)
        return panel

    def _build_event_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(40)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 4, 20, 4)
        self.event_label = QLabel("准备就绪")
        self.event_label.setObjectName("Muted")
        layout.addWidget(self.event_label)
        return bar

    def _icon_button(
        self,
        standard_pixmap: QStyle.StandardPixmap,
        tooltip: str,
    ) -> QPushButton:
        button = QPushButton()
        button.setObjectName("IconButton")
        button.setIcon(self.style().standardIcon(standard_pixmap))
        button.setIconSize(button.iconSize().expandedTo(button.sizeHint()))
        button.setFixedSize(36, 36)
        button.setToolTip(tooltip)
        return button

    def _divider(self) -> QFrame:
        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        return divider

    def _divider_vertical(self) -> QFrame:
        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedWidth(1)
        return divider

    def _restore_settings(self) -> None:
        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        volume = self.settings.value("volume", 80, type=int)
        self.volume_slider.setValue(volume)

    def _tick(self) -> None:
        try:
            self.controller.tick()
        except Exception as error:
            self._show_error(f"程序运行异常：{error}")
        self._render_snapshot()
        self._render_progress()

    def _on_controller_event(self, kind: str, payload) -> None:
        if kind == "library_updated":
            self._refresh_library()
            self._event("音乐库扫描完成")
        elif kind == "snapshot":
            self._render_snapshot()
        elif kind == "event":
            self._event(str(payload))
        elif kind == "error":
            self._show_error(str(payload))
        elif kind == "connection":
            self.connection_label.setText(str(payload))

    def _render_snapshot(self) -> None:
        snapshot = self.controller.snapshot
        signature = json.dumps(
            {
                "room": snapshot.get("room_name"),
                "revision": snapshot.get("queue_revision"),
                "index": snapshot.get("current_index"),
                "epoch": snapshot.get("playback", {}).get("epoch"),
                "playback": snapshot.get("playback", {}).get("playing"),
                "members": snapshot.get("members"),
                "all_ready": snapshot.get("all_online_ready"),
                "role": self.controller.role,
                "connection": self.controller.connection_status,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if signature == self._last_render_signature:
            return
        self._last_render_signature = signature

        in_room = self.controller.is_in_room
        self.room_title.setText(str(snapshot.get("room_name", "本地播放")))
        connected = [
            member
            for member in snapshot.get("members", [])
            if member.get("connected")
        ]
        self.online_label.setText(f"{len(connected)} 人在线")
        self.connection_label.setText(self.controller.connection_status)
        if in_room and self.controller.host_address:
            self.address_label.setText(
                f"Radmin IP {self.controller.host_address} · 端口 {self.controller.port}"
            )
        else:
            self.address_label.setText("本地播放，不会上传文件")
        self.create_button.setVisible(not in_room)
        self.join_button.setVisible(not in_room)
        self.copy_button.setVisible(in_room and self.controller.role == "host")
        self.leave_button.setVisible(in_room)

        queue = snapshot.get("queue", [])
        self.queue_count.setText(f"{len(queue)} 首")
        queue_signature = json.dumps(
            {
                "revision": snapshot.get("queue_revision"),
                "index": snapshot.get("current_index"),
                "items": queue,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if queue_signature != self._queue_signature:
            self._queue_signature = queue_signature
            self._rebuild_queue(queue, int(snapshot.get("current_index", -1)))

        playback = snapshot.get("playback", {})
        current = (
            queue[int(snapshot.get("current_index", -1))]
            if queue and 0 <= int(snapshot.get("current_index", -1)) < len(queue)
            else None
        )
        if current:
            self.track_title.setText(str(current.get("title", "")))
            self.track_artist.setText(str(current.get("artist", "")))
            members = {
                member["member_id"]: member["display_name"]
                for member in snapshot.get("members", [])
            }
            requester = members.get(current.get("added_by"), "未知成员")
            self.requester_label.setText(f"点歌人：{requester}")
            self._set_status(snapshot, connected)
            self.progress_slider.setRange(0, int(playback.get("duration_ms", 0)))
        else:
            self.track_title.setText("还没有播放歌曲")
            self.track_artist.setText("从左侧音乐库双击歌曲加入播放")
            self.requester_label.setText("")
            self.status_label.setText("选择一首歌开始")
            self.progress_slider.setRange(0, 0)

        playing = bool(playback.get("playing"))
        icon = (
            QStyle.StandardPixmap.SP_MediaPause
            if playing
            else QStyle.StandardPixmap.SP_MediaPlay
        )
        self.play_button.setIcon(self.style().standardIcon(icon))

    def _set_status(self, snapshot: dict, connected: list[dict]) -> None:
        playback = snapshot.get("playback", {})
        if self.controller.connection_status == "正在重连":
            self.status_label.setText("正在重新连接房间")
            return
        if not snapshot.get("all_online_ready"):
            track_id = snapshot.get("current_track_id")
            waiting = [
                member.get("display_name", "成员")
                for member in connected
                if member.get("ready_track_id") != track_id
            ]
            if waiting:
                self.status_label.setText(f"等待 {', '.join(waiting[:3])} 准备歌曲")
                return
            self.status_label.setText("正在准备歌曲")
            return
        if playback.get("playing"):
            self.status_label.setText(
                "正在播放" if self.controller.role == "local" else "正在同步播放"
            )
        else:
            self.status_label.setText("已暂停")

    def _render_progress(self) -> None:
        if self._slider_dragging:
            return
        playback = self.controller.snapshot.get("playback", {})
        duration = int(playback.get("duration_ms", 0))
        if duration <= 0:
            self.elapsed_label.setText("0:00")
            self.duration_label.setText("0:00")
            return
        position = min(self.controller.current_position_ms(), duration)
        self.progress_slider.setValue(position)
        self.elapsed_label.setText(_format_time(position))
        self.duration_label.setText(_format_time(duration))

    def _rebuild_queue(self, queue: list[dict], current_index: int) -> None:
        members = {
            member["member_id"]: member["display_name"]
            for member in self.controller.snapshot.get("members", [])
        }
        self.queue_list.clear()
        for index, item in enumerate(queue):
            requester = members.get(item.get("added_by"), "未知成员")
            artist = item.get("artist") or "未知歌手"
            text = (
                f"{index + 1}. {item.get('title', '')}\n"
                f"{artist}  ·  {requester}"
            )
            list_item = QListWidgetItem(text)
            list_item.setData(Qt.ItemDataRole.UserRole, item.get("queue_id"))
            if index == current_index:
                list_item.setIcon(
                    self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
                )
                font = list_item.font()
                font.setBold(True)
                list_item.setFont(font)
            self.queue_list.addItem(list_item)

    def _refresh_library(self) -> None:
        query = self.search_input.text() if hasattr(self, "search_input") else ""
        tracks = self.controller.search_library(query)
        signature = json.dumps(
            [(str(track.path), track.title, track.artist) for track in tracks],
            ensure_ascii=False,
        )
        if signature == self._library_signature:
            return
        self._library_signature = signature
        self.library_list.clear()
        for track in tracks:
            text = f"{track.artist} - {track.title}" if track.artist else track.title
            item = QListWidgetItem(text)
            item.setToolTip(str(track.path))
            item.setData(Qt.ItemDataRole.UserRole, str(track.path))
            self.library_list.addItem(item)

    def _add_library_item(self, item: QListWidgetItem) -> None:
        path = Path(str(item.data(Qt.ItemDataRole.UserRole)))
        media = next(
            (track for track in self.controller.library_tracks() if track.path == path),
            None,
        )
        if media is None:
            return
        self.controller.add_track(media)
        self._event(f"正在准备《{media.title}》")

    def _play_queue_item(self, item: QListWidgetItem) -> None:
        queue_id = item.data(Qt.ItemDataRole.UserRole)
        if queue_id:
            self.controller.play_queue_item(str(queue_id))

    def _choose_music_folder(self) -> None:
        initial = self.settings.value("library_folder", "", type=str)
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择音乐目录",
            initial,
        )
        if not directory:
            return
        self.settings.setValue("library_folder", directory)
        self._start_library_scan(Path(directory))

    def _start_library_scan(self, directory: Path) -> None:
        self._event(f"正在扫描 {directory}")
        self.controller.scan_library_async(directory)

    def _create_room(self) -> None:
        dialog = CreateRoomDialog(display_name=self._display_name, parent=self)
        if dialog.exec() != CreateRoomDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self._display_name = values["display_name"]
        self.settings.setValue("display_name", self._display_name)
        try:
            info = self.controller.create_room(**values)
        except Exception as error:
            QMessageBox.critical(self, "创建房间失败", str(error))
            return
        self._event(
            f"房间已创建：{info['address']}:{info['port']}，口令 {info['password']}"
        )
        self._last_render_signature = ""
        self._render_snapshot()

    def _join_room(self) -> None:
        dialog = JoinRoomDialog(display_name=self._display_name, parent=self)
        if dialog.exec() != JoinRoomDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self._display_name = values["display_name"]
        self.settings.setValue("display_name", self._display_name)
        try:
            self.controller.join_room(**values)
        except Exception as error:
            QMessageBox.critical(self, "加入房间失败", str(error))
            return
        self._event("正在同步房间")
        self._last_render_signature = ""
        self._render_snapshot()

    def _leave_room(self) -> None:
        answer = QMessageBox.question(
            self,
            "退出房间",
            "退出后会停止播放并清理本次房间缓存，是否继续？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.controller.leave_room()
        self._last_render_signature = ""
        self._queue_signature = ""
        self._render_snapshot()
        self._event("已退出房间，临时缓存已清理")

    def _copy_room_info(self) -> None:
        QApplication.clipboard().setText(self.controller.room_info_text())
        self._event("房间信息已复制")

    def _slider_pressed(self) -> None:
        self._slider_dragging = True

    def _slider_released(self) -> None:
        self._slider_dragging = False
        self.controller.seek(self.progress_slider.value())

    def _event(self, text: str) -> None:
        self.event_label.setObjectName("Muted")
        self.event_label.style().unpolish(self.event_label)
        self.event_label.style().polish(self.event_label)
        self.event_label.setText(text)

    def _show_error(self, text: str) -> None:
        self.event_label.setObjectName("ErrorText")
        self.event_label.style().unpolish(self.event_label)
        self.event_label.style().polish(self.event_label)
        self.event_label.setText(text)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("volume", self.volume_slider.value())
        self.settings.setValue("display_name", self._display_name)
        self._timer.stop()
        self.controller.close()
        super().closeEvent(event)

