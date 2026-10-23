APP_STYLE = """
* {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    font-size: 15px;
    color: #1F2329;
}
QMainWindow, QWidget#Page {
    background: #FFFFFF;
}
QWidget#Sidebar {
    background: #F7F8FA;
}
QLabel#RoomTitle {
    font-size: 18px;
    font-weight: 600;
}
QLabel#SectionTitle {
    font-size: 13px;
    font-weight: 600;
    color: #646A73;
}
QLabel#Secondary {
    font-size: 13px;
    color: #646A73;
}
QLabel#Muted {
    font-size: 12px;
    color: #8F959E;
}
QLabel#TrackTitle {
    font-size: 24px;
    font-weight: 600;
}
QLabel#StatusText {
    font-size: 13px;
    color: #646A73;
}
QLabel#ErrorText {
    font-size: 13px;
    color: #F54A45;
}
QLineEdit {
    background: #F7F8FA;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 14px;
}
QLineEdit:focus {
    background: #FFFFFF;
    border: 1px solid #3370FF;
}
QPushButton {
    background: #FFFFFF;
    border: 1px solid #E5E6EB;
    border-radius: 6px;
    padding: 7px 12px;
    font-size: 14px;
}
QPushButton:hover {
    background: #F7F8FA;
}
QPushButton#Primary {
    background: #3370FF;
    color: #FFFFFF;
    border: none;
}
QPushButton#Primary:hover {
    background: #2B5FD9;
}
QPushButton#Danger {
    color: #F54A45;
    border-color: #F8C9C7;
}
QPushButton#IconButton {
    border: none;
    background: transparent;
    border-radius: 18px;
    padding: 6px;
}
QPushButton#IconButton:hover {
    background: #F0F2F5;
}
QListWidget {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget::item {
    min-height: 46px;
    padding: 5px 10px;
    border-radius: 6px;
}
QListWidget::item:hover {
    background: #F7F8FA;
}
QListWidget::item:selected {
    background: #E1EAFF;
    color: #1F2329;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #E5E6EB;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #3370FF;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 12px;
    height: 12px;
    margin: -4px 0;
    background: #FFFFFF;
    border: 2px solid #3370FF;
    border-radius: 6px;
}
QFrame#Divider {
    background: #E5E6EB;
    max-height: 1px;
}
QFrame#Panel {
    background: #FFFFFF;
}
QDialog {
    background: #FFFFFF;
}
QMenu {
    background: #FFFFFF;
    border: 1px solid #E5E6EB;
    padding: 4px;
}
QMenu::item {
    padding: 7px 22px;
    border-radius: 4px;
}
QMenu::item:selected {
    background: #F7F8FA;
}
"""

