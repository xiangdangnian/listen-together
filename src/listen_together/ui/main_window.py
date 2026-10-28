import json
import os
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QColor, QIcon, QTextCharFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QSplitter,
    QStyle,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from listen_together.app_controller import AppController
from listen_together.library.lyrics import LyricLine, parse_lrc, timed_lyric_index
from listen_together.library.models import MediaFile
from listen_together.ui.dialogs import (
    AppearanceDialog,
    CreateRoomDialog,
    JoinRoomDialog,
)
from listen_together.ui.icons import lucide_pixmap
from listen_together.ui.theme import PRESET_BY_ID, THEMES, build_app_style
from listen_together.ui.window_effects import apply_windows_glass, apply_windows_titlebar


def _format_time(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"


MODE_LABELS = {
    "sequential": "顺序",
    "loop": "循环",
    "shuffle": "随机",
}


class QueueListWidget(QListWidget):
    reorder_requested = Signal(str, object)
    remove_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
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
        self._queue_current_index = -1
        self._library_signature = ""
        self._slider_dragging = False
        self._lyrics_track_id: str | None = None
        self._lyric_lines: list[LyricLine] = []
        self._lyric_index = -2
        self._sidebar_sizes = [300, 800, 340]
        self._left_width = 300
        self._center_width = 800
        self._right_width = 340
        self._appearance_preset = self._initial_appearance_preset()
        preset = PRESET_BY_ID[self._appearance_preset]
        self._theme_name = preset["theme"]
        self._window_effect = preset["effect"]
        self._opacity_percent = min(
            max(60, self.settings.value("window_opacity", 100, type=int)),
            100,
        )
        self._display_name = self._initial_display_name()
        self.setWindowTitle("一起听音乐")
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(
            build_app_style(self._theme_name, effect=self._window_effect)
        )
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

    def _initial_appearance_preset(self) -> str:
        saved = self.settings.value("appearance_preset", "", type=str)
        if saved in PRESET_BY_ID:
            return saved
        legacy_theme = self.settings.value("theme", "light", type=str)
        legacy_effect = self.settings.value("window_effect", "solid", type=str)
        for preset_id, preset in PRESET_BY_ID.items():
            if (
                preset["theme"] == legacy_theme
                and preset["effect"] == legacy_effect
            ):
                return preset_id
        return "light"
    def _build_ui(self) -> None:
        page = QWidget()
        page.setObjectName("Page")
        self.setCentralWidget(page)
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_top_bar())
        root.addWidget(self._divider())

        self.left_panel = self._build_library_panel()
        self.player_panel = self._build_player_panel()
        self.right_panel = self._build_queue_panel()
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setChildrenCollapsible(True)
        self.content_splitter.setHandleWidth(1)
        self.content_splitter.addWidget(self.left_panel)
        self.content_splitter.addWidget(self.player_panel)
        self.content_splitter.addWidget(self.right_panel)
        self.content_splitter.setStretchFactor(0, 0)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setStretchFactor(2, 0)
        self.content_splitter.setSizes(self._sidebar_sizes)
        self.content_splitter.splitterMoved.connect(self._remember_splitter_sizes)
        root.addWidget(self.content_splitter, 1)
        root.addWidget(self._divider())
        root.addWidget(self._build_event_bar())

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
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

        self.left_toggle_button = self._sidebar_toggle_button("隐藏左侧栏")
        self.right_toggle_button = self._sidebar_toggle_button("隐藏右侧栏")
        self.left_toggle_button.clicked.connect(self._toggle_left_panel)
        self.right_toggle_button.clicked.connect(self._toggle_right_panel)
        layout.addWidget(self.left_toggle_button)
        layout.addWidget(self.right_toggle_button)

        self.create_button = QPushButton("创建房间")
        self.create_button.setObjectName("Primary")
        self.join_button = QPushButton("加入房间")
        self.appearance_button = QPushButton("外观")
        self.copy_button = QPushButton("复制房间信息")
        self.leave_button = QPushButton("退出房间")
        self.leave_button.setObjectName("Danger")
        self.create_button.clicked.connect(self._create_room)
        self.join_button.clicked.connect(self._join_room)
        self.appearance_button.clicked.connect(self._choose_appearance)
        self.copy_button.clicked.connect(self._copy_room_info)
        self.leave_button.clicked.connect(self._leave_room)
        for button in (
            self.appearance_button,
            self.create_button,
            self.join_button,
            self.copy_button,
            self.leave_button,
        ):
            button.setMinimumHeight(34)
            button.setAccessibleName(button.text())
        layout.addWidget(self.appearance_button)
        layout.addWidget(self.create_button)
        layout.addWidget(self.join_button)
        layout.addWidget(self.copy_button)
        layout.addWidget(self.leave_button)
        return bar

    def _build_library_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("Sidebar")
        panel.setMinimumWidth(220)
        panel.setMaximumWidth(520)
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
        self.library_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.library_list.itemDoubleClicked.connect(self._add_library_item)
        self.library_list.itemSelectionChanged.connect(self._update_library_actions)
        layout.addWidget(self.library_list, 1)
        self.add_folder_button = QPushButton("选择目录")
        self.add_selected_button = QPushButton("加入选中")
        self.add_all_button = QPushButton("全部加入")
        for button in (
            self.add_folder_button,
            self.add_selected_button,
            self.add_all_button,
        ):
            button.setMinimumHeight(34)
            button.setAccessibleName(button.text())
        self.add_folder_button.clicked.connect(self._choose_music_folder)
        self.add_selected_button.setEnabled(False)
        self.add_selected_button.clicked.connect(self._add_selected_library_tracks)
        self.add_all_button.clicked.connect(self._add_all_library_tracks)
        layout.addWidget(self.add_folder_button)
        library_actions = QHBoxLayout()
        library_actions.addWidget(self.add_selected_button, 1)
        library_actions.addWidget(self.add_all_button, 1)
        layout.addLayout(library_actions)
        return panel

    def _build_player_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("Panel")
        panel.setMinimumWidth(480)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(40, 28, 40, 24)
        layout.setSpacing(12)

        layout.addStretch(1)
        self.lyrics_view = QTextBrowser()
        self.lyrics_view.setObjectName("Lyrics")
        self.lyrics_view.setFixedHeight(250)
        self.lyrics_view.setOpenExternalLinks(False)
        self.lyrics_view.hide()
        layout.addWidget(self.lyrics_view)

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
        self.volume_icon = QLabel()
        self.volume_icon.setPixmap(
            lucide_pixmap(
                "volume-2",
                color=THEMES[self._theme_name]["secondary"],
                size=18,
            )
        )
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedWidth(150)
        self.volume_slider.valueChanged.connect(self.controller.set_volume)
        volume_row.addWidget(self.volume_icon)
        volume_row.addWidget(self.volume_slider)
        self.mode_button = QPushButton("顺序")
        self.mode_button.setObjectName("ModeButton")
        self.mode_button.setFixedSize(86, 32)
        self.mode_button.setToolTip("切换顺序、循环或随机播放")
        self.mode_button.setAccessibleName("播放模式")
        self.mode_button.clicked.connect(self._cycle_playback_mode)
        volume_row.addWidget(self.mode_button)
        volume_row.addStretch(1)
        layout.addLayout(volume_row)
        layout.addStretch(1)
        return panel

    def _build_queue_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("Sidebar")
        panel.setMinimumWidth(260)
        panel.setMaximumWidth(620)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 18, 16, 12)
        layout.setSpacing(10)
        members_row = QHBoxLayout()
        members_heading = QLabel("在线成员")
        members_heading.setObjectName("SectionTitle")
        self.listening_time_label = QLabel("听歌 0:00:00")
        self.listening_time_label.setObjectName("Muted")
        members_row.addWidget(members_heading)
        members_row.addStretch(1)
        members_row.addWidget(self.listening_time_label)
        self.members_label = QLabel("本机")
        self.members_label.setObjectName("Secondary")
        self.members_label.setWordWrap(True)
        layout.addLayout(members_row)
        layout.addWidget(self.members_label)
        heading_row = QHBoxLayout()
        heading = QLabel("共享歌单")
        heading.setObjectName("SectionTitle")
        self.queue_count = QLabel("0 首")
        self.queue_count.setObjectName("Muted")
        self.locate_button = QPushButton("定位")
        self.locate_button.setObjectName("CompactButton")
        self.locate_button.setFixedSize(62, 30)
        self.locate_button.setIconSize(QSize(14, 14))
        self.locate_button.setToolTip("定位到正在播放的歌曲")
        self.locate_button.setAccessibleName("定位当前歌曲")
        self.locate_button.setEnabled(False)
        self.locate_button.clicked.connect(self._locate_current_track)
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        heading_row.addWidget(self.queue_count)
        heading_row.addWidget(self.locate_button)
        layout.addLayout(heading_row)
        self.queue_list = QueueListWidget()
        self.queue_list.itemDoubleClicked.connect(self._play_queue_item)
        self.queue_list.itemSelectionChanged.connect(self._update_queue_actions)
        self.queue_list.reorder_requested.connect(self.controller.move_queue_item)
        self.queue_list.remove_requested.connect(self.controller.remove_queue_item)
        layout.addWidget(self.queue_list, 1)
        self.delete_queue_button = QPushButton("删除选中歌曲")
        self.delete_queue_button.setObjectName("Danger")
        self.delete_queue_button.setMinimumHeight(34)
        self.delete_queue_button.setAccessibleName("删除选中的歌曲")
        self.delete_queue_button.setEnabled(False)
        self.delete_queue_button.clicked.connect(self._remove_selected_queue_item)
        layout.addWidget(self.delete_queue_button)
        return panel

    def _build_event_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("EventBar")
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
        button.setAccessibleName(tooltip)
        return button

    def _sidebar_toggle_button(self, tooltip: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("IconButton")
        button.setFixedSize(30, 30)
        button.setIconSize(QSize(16, 16))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        return button

    def _toggle_left_panel(self) -> None:
        self._remember_splitter_sizes()
        self.left_panel.setVisible(self.left_panel.isHidden())
        self._apply_splitter_sizes()
        self._update_sidebar_buttons()

    def _toggle_right_panel(self) -> None:
        self._remember_splitter_sizes()
        self.right_panel.setVisible(self.right_panel.isHidden())
        self._apply_splitter_sizes()
        self._update_sidebar_buttons()

    def _remember_splitter_sizes(self) -> None:
        if not hasattr(self, "content_splitter"):
            return
        sizes = self.content_splitter.sizes()
        if len(sizes) != 3:
            return
        if not self.left_panel.isHidden() and sizes[0] > 0:
            self._left_width = sizes[0]
        if not self.right_panel.isHidden() and sizes[2] > 0:
            self._right_width = sizes[2]
        self._center_width = max(480, sizes[1])
        self._sidebar_sizes = [
            self._left_width,
            self._center_width,
            self._right_width,
        ]

    def _apply_splitter_sizes(self) -> None:
        left = self._left_width if not self.left_panel.isHidden() else 0
        right = self._right_width if not self.right_panel.isHidden() else 0
        center = max(480, self.width() - left - right)
        self.content_splitter.setSizes([left, center, right])

    def _update_sidebar_buttons(self) -> None:
        color = THEMES[self._theme_name]["secondary"]
        left_icon = "chevron-left" if not self.left_panel.isHidden() else "chevron-right"
        right_icon = "chevron-right" if not self.right_panel.isHidden() else "chevron-left"
        self.left_toggle_button.setIcon(
            QIcon(lucide_pixmap(left_icon, color=color, size=16))
        )
        self.right_toggle_button.setIcon(
            QIcon(lucide_pixmap(right_icon, color=color, size=16))
        )
        self.left_toggle_button.setToolTip(
            "隐藏左侧栏" if not self.left_panel.isHidden() else "显示左侧栏"
        )
        self.right_toggle_button.setToolTip(
            "隐藏右侧栏" if not self.right_panel.isHidden() else "显示右侧栏"
        )
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
        self._apply_appearance_preset(
            self._appearance_preset,
            self._opacity_percent,
        )
        saved_sizes = self.settings.value("splitter_sizes", self._sidebar_sizes)
        if isinstance(saved_sizes, list) and len(saved_sizes) == 3:
            self._sidebar_sizes = [int(value) for value in saved_sizes]
            self._left_width = self._sidebar_sizes[0]
            self._center_width = self._sidebar_sizes[1]
            self._right_width = self._sidebar_sizes[2]
        self.left_panel.setVisible(
            self.settings.value("left_panel_visible", True, type=bool)
        )
        self.right_panel.setVisible(
            self.settings.value("right_panel_visible", True, type=bool)
        )
        self.content_splitter.setSizes(self._sidebar_sizes)
        self._apply_splitter_sizes()
        self._update_sidebar_buttons()
        volume = self.settings.value("volume", 80, type=int)
        self.volume_slider.setValue(volume)

    def _tick(self) -> None:
        try:
            self.controller.tick()
        except Exception as error:
            self._show_error(f"程序运行异常：{error}")
        self._render_snapshot()
        self._render_progress()
        self._render_listening_time()

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

    def _render_listening_time(self) -> None:
        total_seconds = max(0, self.controller.listening_time_ms() // 1_000)
        hours, remainder = divmod(total_seconds, 3_600)
        minutes, seconds = divmod(remainder, 60)
        self.listening_time_label.setText(
            f"听歌 {hours}:{minutes:02d}:{seconds:02d}"
        )
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
                "playback_mode": snapshot.get("playback_mode", "sequential"),
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
        self.members_label.setText(
            " · ".join(member.get("display_name", "成员") for member in connected)
            or "暂无在线成员"
        )
        mode = str(snapshot.get("playback_mode", "sequential"))
        self._update_mode_button(mode)
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
                "items": queue,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        current_index = int(snapshot.get("current_index", -1))
        if queue_signature != self._queue_signature:
            self._queue_signature = queue_signature
            self._rebuild_queue(queue, current_index)
        else:
            self._update_queue_current_marker(current_index)

        playback = snapshot.get("playback", {})
        current = (
            queue[int(snapshot.get("current_index", -1))]
            if queue and 0 <= int(snapshot.get("current_index", -1)) < len(queue)
            else None
        )
        if current:
            self.track_title.setText(str(current.get("title", "")))
            self.track_artist.setText(str(current.get("artist", "")))
            lyrics = str(current.get("lyrics", "")).strip()
            if lyrics:
                self.lyrics_view.show()
                self.track_artist.show()
                self.requester_label.show()
                self._show_lyrics_for_track(current)
            else:
                self._clear_lyrics()
                self.track_artist.hide()
                self.requester_label.hide()
            members = {
                member["member_id"]: member["display_name"]
                for member in snapshot.get("members", [])
            }
            requester = members.get(current.get("added_by"), "未知成员")
            self.requester_label.setText(f"点歌人：{requester}")
            self._set_status(snapshot, connected)
            self.progress_slider.setRange(0, int(playback.get("duration_ms", 0)))
            self.locate_button.setEnabled(True)
        else:
            self.track_title.setText("还没有播放歌曲")
            self.track_artist.setText("从左侧音乐库双击歌曲加入播放")
            self.requester_label.setText("")
            self._clear_lyrics()
            self.track_artist.hide()
            self.requester_label.hide()
            self.status_label.setText("选择一首歌开始")
            self.progress_slider.setRange(0, 0)
            self.locate_button.setEnabled(False)

        playing = bool(playback.get("playing"))
        icon = (
            QStyle.StandardPixmap.SP_MediaPause
            if playing
            else QStyle.StandardPixmap.SP_MediaPlay
        )
        self.play_button.setIcon(self.style().standardIcon(icon))

    def _update_mode_button(self, mode: str) -> None:
        icon_name = {
            "sequential": "list",
            "loop": "repeat-2",
            "shuffle": "shuffle",
        }.get(mode, "list")
        label = MODE_LABELS.get(mode, "顺序")
        color = THEMES[self._theme_name]["secondary"]
        self.mode_button.setText(label)
        self.mode_button.setIcon(
            QIcon(lucide_pixmap(icon_name, color=color, size=16))
        )
        self.mode_button.setToolTip(f"当前：{label}播放，点击切换")

    def _locate_current_track(self) -> None:
        index = int(self.controller.snapshot.get("current_index", -1))
        item = self.queue_list.item(index) if index >= 0 else None
        if item is None:
            return
        self.queue_list.scrollToItem(
            item,
            QAbstractItemView.ScrollHint.PositionAtCenter,
        )
        self.queue_list.viewport().update()
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
        position = min(self.controller.current_position_ms(), max(0, duration))
        self._update_lyrics_position(position)
        if duration <= 0:
            self.elapsed_label.setText("0:00")
            self.duration_label.setText("0:00")
            return
        self.progress_slider.setValue(position)
        self.elapsed_label.setText(_format_time(position))
        self.duration_label.setText(_format_time(duration))
        self._update_lyrics_position(position)

    def _show_lyrics_for_track(self, track: dict) -> None:
        track_id = str(track.get("track_id", ""))
        if track_id == self._lyrics_track_id:
            return
        self._lyrics_track_id = track_id
        self._lyric_lines = parse_lrc(str(track.get("lyrics_lrc", "")))
        self._lyric_index = -2
        if self._lyric_lines:
            self.lyrics_view.setPlainText("\n".join(line.text for line in self._lyric_lines))
        else:
            self.lyrics_view.setPlainText(str(track.get("lyrics", "")))
            self.lyrics_view.moveCursor(QTextCursor.MoveOperation.Start)
        text_option = self.lyrics_view.document().defaultTextOption()
        text_option.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.lyrics_view.document().setDefaultTextOption(text_option)
        self._set_lyric_document_padding()
        self.lyrics_view.viewport().update()
        self._update_lyrics_position(self.controller.current_position_ms())

    def _set_lyric_document_padding(self) -> None:
        document = self.lyrics_view.document()
        root = document.rootFrame()
        frame_format = root.frameFormat()
        padding = max(40, self.lyrics_view.viewport().height() // 2 - 18)
        frame_format.setTopMargin(padding)
        frame_format.setBottomMargin(padding)
        root.setFrameFormat(frame_format)

    def _apply_lyric_format(self, index: int, *, active: bool) -> None:
        block = self.lyrics_view.document().findBlockByNumber(index)
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        block_format = cursor.blockFormat()
        block_format.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        cursor.setBlockFormat(block_format)
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        colors = THEMES[self._theme_name]
        char_format = QTextCharFormat()
        char_format.setForeground(
            QColor(colors["text"] if active else colors["secondary"])
        )
        char_format.setFontPointSize(20 if active else 11)
        char_format.setFontWeight(700 if active else 400)
        cursor.setCharFormat(char_format)

    def _center_lyric_block(self, index: int) -> None:
        block = self.lyrics_view.document().findBlockByNumber(index)
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        self.lyrics_view.setTextCursor(cursor)
        self.lyrics_view.ensureCursorVisible()
        layout = block.layout()
        if layout is None or layout.lineCount() == 0:
            return
        text_center_y = layout.position().y() + layout.lineAt(0).naturalTextRect().center().y()
        scroll_bar = self.lyrics_view.verticalScrollBar()
        scroll_bar.setValue(
            round(text_center_y - self.lyrics_view.viewport().height() / 2)
        )

    def _update_lyrics_position(self, position_ms: int) -> None:
        if not self._lyric_lines or self.lyrics_view.isHidden():
            return
        index = timed_lyric_index(self._lyric_lines, position_ms)
        if index == self._lyric_index:
            return
        previous_index = self._lyric_index
        self._lyric_index = index
        if previous_index == -2:
            for block_index in range(len(self._lyric_lines)):
                self._apply_lyric_format(block_index, active=False)
        elif previous_index >= 0:
            self._apply_lyric_format(previous_index, active=False)
        if index < 0:
            self._center_lyric_block(0)
        else:
            self._apply_lyric_format(index, active=True)
            self._center_lyric_block(index)
        self.lyrics_view.viewport().update()

    def _clear_lyrics(self) -> None:
        self.lyrics_view.hide()
        self.lyrics_view.setPlainText("")
        self._lyrics_track_id = None
        self._lyric_lines = []
        self._lyric_index = -2

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._lyric_lines and not self.lyrics_view.isHidden():
            self._set_lyric_document_padding()
            if self._lyric_index >= 0:
                self._center_lyric_block(self._lyric_index)
    def _rebuild_queue(self, queue: list[dict], current_index: int) -> None:
        members = {
            member["member_id"]: member["display_name"]
            for member in self.controller.snapshot.get("members", [])
        }
        selected_ids = {
            str(item.data(Qt.ItemDataRole.UserRole))
            for item in self.queue_list.selectedItems()
        }
        scroll_value = self.queue_list.verticalScrollBar().value()
        self.queue_list.setUpdatesEnabled(False)
        try:
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
                if str(item.get("queue_id")) in selected_ids:
                    list_item.setSelected(True)
        finally:
            self.queue_list.setUpdatesEnabled(True)
            self.queue_list.verticalScrollBar().setValue(scroll_value)
            self._queue_current_index = current_index
            self._update_queue_actions()
            self.queue_list.viewport().update()

    def _update_queue_current_marker(self, current_index: int) -> None:
        if current_index == self._queue_current_index:
            return
        for row in (self._queue_current_index, current_index):
            item = self.queue_list.item(row) if row >= 0 else None
            if item is None:
                continue
            font = item.font()
            font.setBold(row == current_index)
            item.setFont(font)
            item.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
                if row == current_index
                else QIcon()
            )
        self._queue_current_index = current_index
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
        self.library_list.setUpdatesEnabled(False)
        try:
            self.library_list.clear()
            for track in tracks:
                text = (
                    f"{track.artist} - {track.title}" if track.artist else track.title
                )
                item = QListWidgetItem(text)
                item.setToolTip(str(track.path))
                item.setData(Qt.ItemDataRole.UserRole, str(track.path))
                self.library_list.addItem(item)
        finally:
            self.library_list.setUpdatesEnabled(True)
            self.library_list.viewport().update()

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

    def _add_all_library_tracks(self) -> None:
        tracks = self.controller.library_tracks()
        if not tracks:
            self._event("当前音乐目录没有可导入的歌曲")
            return
        self.controller.add_tracks(tracks)
        self._event(f"正在导入当前目录的 {len(tracks)} 首歌曲")

    def _add_selected_library_tracks(self) -> None:
        selected_paths = {
            Path(str(item.data(Qt.ItemDataRole.UserRole)))
            for item in self.library_list.selectedItems()
        }
        tracks = [
            track
            for track in self.controller.library_tracks()
            if track.path in selected_paths
        ]
        if not tracks:
            self._event("请先选择要加入歌单的歌曲")
            return
        self.controller.add_tracks(tracks)
        self._event(f"正在导入选中的 {len(tracks)} 首歌曲")

    def _update_library_actions(self) -> None:
        self.add_selected_button.setEnabled(bool(self.library_list.selectedItems()))

    def _play_queue_item(self, item: QListWidgetItem) -> None:
        queue_id = item.data(Qt.ItemDataRole.UserRole)
        if queue_id:
            self.controller.play_queue_item(str(queue_id))

    def _remove_selected_queue_item(self) -> None:
        queue_ids = [
            str(item.data(Qt.ItemDataRole.UserRole))
            for item in self.queue_list.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole)
        ]
        if not queue_ids:
            return
        self.delete_queue_button.setEnabled(False)
        self._event(f"正在删除选中的 {len(queue_ids)} 首歌曲")
        self.controller.remove_queue_items(queue_ids)

    def _update_queue_actions(self) -> None:
        selected = self.queue_list.selectedItems()
        if not selected:
            self.delete_queue_button.setText("删除选中歌曲")
            self.delete_queue_button.setEnabled(False)
            self.delete_queue_button.setToolTip("先在共享歌单中选择歌曲")
            return
        queue = self.controller.snapshot.get("queue", [])
        selected_ids = {
            str(item.data(Qt.ItemDataRole.UserRole)) for item in selected
        }
        selected_tracks = [
            item for item in queue if str(item.get("queue_id")) in selected_ids
        ]
        is_host = self.controller.role in {"local", "host"}
        allowed = [
            item
            for item in selected_tracks
            if is_host or item.get("added_by") == self.controller.member_id
        ]
        self.delete_queue_button.setText(f"删除选中 ({len(selected)})")
        self.delete_queue_button.setEnabled(bool(allowed))
        if allowed:
            self.delete_queue_button.setToolTip("一次删除所有选中的歌曲")
        else:
            self.delete_queue_button.setToolTip("只能删除自己加入的歌曲")

    def _cycle_playback_mode(self) -> None:
        mode = self.controller.cycle_playback_mode()
        self._event(f"播放模式：{MODE_LABELS.get(mode, '顺序')}")

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

    def _choose_appearance(self) -> None:
        dialog = AppearanceDialog(
            preset_id=self._appearance_preset,
            opacity_percent=self._opacity_percent,
            parent=self,
        )
        if dialog.exec() != AppearanceDialog.DialogCode.Accepted:
            return
        preset_id, opacity = dialog.values()
        self._apply_appearance_preset(preset_id, opacity)
        self._event(f"已切换为{PRESET_BY_ID[self._appearance_preset]['label']}外观")

    def _apply_appearance_preset(self, preset_id: str, opacity_percent: int) -> None:
        preset = PRESET_BY_ID.get(preset_id, PRESET_BY_ID["light"])
        self._appearance_preset = preset["id"]
        self._apply_appearance(
            preset["theme"],
            opacity_percent,
            preset["effect"],
        )

    def _apply_appearance(
        self,
        theme_name: str,
        opacity_percent: int,
        window_effect: str = "solid",
    ) -> None:
        self._theme_name = theme_name if theme_name in THEMES else "light"
        self._opacity_percent = min(max(60, int(opacity_percent)), 100)
        self._window_effect = (
            window_effect
            if window_effect in {"solid", "acrylic", "transparent"}
            else "solid"
        )
        glass = self._window_effect in {"acrylic", "transparent"}
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, glass)
        self.setStyleSheet(
            build_app_style(self._theme_name, effect=self._window_effect)
        )
        self.volume_icon.setPixmap(
            lucide_pixmap(
                "volume-2",
                color=THEMES[self._theme_name]["secondary"],
                size=18,
            )
        )
        self.locate_button.setIcon(
            QIcon(
                lucide_pixmap(
                    "locate-fixed",
                    color=THEMES[self._theme_name]["secondary"],
                    size=16,
                )
            )
        )
        self._update_mode_button(
            str(self.controller.snapshot.get("playback_mode", "sequential"))
        )
        effective_opacity = self._opacity_percent
        if self._window_effect == "acrylic":
            effective_opacity = max(85, effective_opacity)
        self.setWindowOpacity(effective_opacity / 100)
        apply_windows_glass(self, self._window_effect)
        apply_windows_titlebar(
            self,
            background=THEMES[self._theme_name]["background"],
            foreground=THEMES[self._theme_name]["text"],
            dark=self._theme_name in {"dark", "midnight"},
        )
        self._lyric_index = -2
        self._update_lyrics_position(self.controller.current_position_ms())
        self._update_sidebar_buttons()
        for widget in (self.library_list, self.queue_list, self.lyrics_view):
            widget.viewport().update()
        self.update()

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
        self._remember_splitter_sizes()
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("splitter_sizes", self._sidebar_sizes)
        self.settings.setValue("left_panel_visible", not self.left_panel.isHidden())
        self.settings.setValue("right_panel_visible", not self.right_panel.isHidden())
        self.settings.setValue("volume", self.volume_slider.value())
        self.settings.setValue("display_name", self._display_name)
        self.settings.setValue("appearance_preset", self._appearance_preset)
        self.settings.setValue("theme", self._theme_name)
        self.settings.setValue("window_opacity", self._opacity_percent)
        self.settings.setValue("window_effect", self._window_effect)
        self._timer.stop()
        self.controller.close()
        super().closeEvent(event)
