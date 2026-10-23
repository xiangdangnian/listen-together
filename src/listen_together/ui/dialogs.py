import secrets

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)


class CreateRoomDialog(QDialog):
    def __init__(
        self,
        *,
        display_name: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("创建房间")
        self.setMinimumWidth(380)
        self.room_name = QLineEdit("周末听歌")
        self.display_name = QLineEdit(display_name)
        self.password = QLineEdit(f"{secrets.randbelow(1_000_000):06d}")
        self.password.setMaxLength(12)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(43871)

        form = QFormLayout()
        form.setSpacing(12)
        form.addRow("房间名", self.room_name)
        form.addRow("显示名", self.display_name)
        form.addRow("房间口令", self.password)
        form.addRow("控制端口", self.port)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("创建")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(18)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _validate(self) -> None:
        if not self.room_name.text().strip() or not self.display_name.text().strip():
            QMessageBox.warning(self, "信息不完整", "房间名和显示名不能为空。")
            return
        if not self.password.text().strip():
            QMessageBox.warning(self, "信息不完整", "房间口令不能为空。")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "room_name": self.room_name.text().strip(),
            "display_name": self.display_name.text().strip(),
            "password": self.password.text().strip(),
            "port": self.port.value(),
        }


class JoinRoomDialog(QDialog):
    def __init__(self, *, display_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("加入房间")
        self.setMinimumWidth(380)
        self.host = QLineEdit()
        self.host.setPlaceholderText("房主的 Radmin IPv4")
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(43871)
        self.password = QLineEdit()
        self.password.setPlaceholderText("6 位房间口令")
        self.display_name = QLineEdit(display_name)

        form = QFormLayout()
        form.setSpacing(12)
        form.addRow("房主 IP", self.host)
        form.addRow("端口", self.port)
        form.addRow("房间口令", self.password)
        form.addRow("显示名", self.display_name)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("加入")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(18)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _validate(self) -> None:
        if (
            not self.host.text().strip()
            or not self.password.text().strip()
            or not self.display_name.text().strip()
        ):
            QMessageBox.warning(self, "信息不完整", "请填写 IP、口令和显示名。")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "host": self.host.text().strip(),
            "port": self.port.value(),
            "password": self.password.text().strip(),
            "display_name": self.display_name.text().strip(),
        }

