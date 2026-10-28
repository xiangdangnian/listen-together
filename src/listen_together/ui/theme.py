THEMES = {
    "light": {
        "label": "浅色",
        "background": "#FFFFFF",
        "sidebar": "#F7F8FA",
        "input": "#F7F8FA",
        "hover": "#F0F2F5",
        "divider": "#E5E6EB",
        "text": "#1F2329",
        "secondary": "#646A73",
        "muted": "#8F959E",
        "accent": "#3370FF",
        "accent_hover": "#2B5FD9",
        "accent_soft": "#E1EAFF",
        "accent_pale": "#F0F4FF",
        "error": "#F54A45",
        "on_accent": "#FFFFFF",
    },
    "warm": {
        "label": "暖色",
        "background": "#FFFDF8",
        "sidebar": "#F7F1E8",
        "input": "#F7F1E8",
        "hover": "#EFE5D8",
        "divider": "#E5D9C9",
        "text": "#2B2520",
        "secondary": "#6E6258",
        "muted": "#94877C",
        "accent": "#B8652A",
        "accent_hover": "#975020",
        "accent_soft": "#F3DFCE",
        "accent_pale": "#FBF0E5",
        "error": "#C9413C",
        "on_accent": "#FFFFFF",
    },
    "cool": {
        "label": "冷色",
        "background": "#F8FBFF",
        "sidebar": "#EDF4FB",
        "input": "#EDF4FB",
        "hover": "#E3EDF7",
        "divider": "#D7E3ED",
        "text": "#1E2A33",
        "secondary": "#5D6D79",
        "muted": "#84939F",
        "accent": "#2477A8",
        "accent_hover": "#1B618A",
        "accent_soft": "#D7EAF7",
        "accent_pale": "#EAF5FC",
        "error": "#C74444",
        "on_accent": "#FFFFFF",
    },
    "dark": {
        "label": "深色",
        "background": "#1B1D21",
        "sidebar": "#24272C",
        "input": "#2C3036",
        "hover": "#30343A",
        "divider": "#393D45",
        "text": "#F2F3F5",
        "secondary": "#B7BCC5",
        "muted": "#8D939D",
        "accent": "#6E9BFF",
        "accent_hover": "#8AAEFF",
        "accent_soft": "#334464",
        "accent_pale": "#263248",
        "error": "#FF7370",
        "on_accent": "#111827",
    },
    "mint": {
        "label": "薄荷",
        "background": "#F5FBF8",
        "sidebar": "#E8F4EE",
        "input": "#E8F4EE",
        "hover": "#DDEEE5",
        "divider": "#CFE2D8",
        "text": "#1E2B26",
        "secondary": "#536861",
        "muted": "#7A8C85",
        "accent": "#146F50",
        "accent_hover": "#0F5B40",
        "accent_soft": "#CDEBDD",
        "accent_pale": "#E4F5ED",
        "error": "#B84040",
        "on_accent": "#FFFFFF",
    },
    "rose": {
        "label": "玫瑰",
        "background": "#FFF8FA",
        "sidebar": "#F8EBEF",
        "input": "#F8EBEF",
        "hover": "#F1DDE3",
        "divider": "#E5CED6",
        "text": "#2D2024",
        "secondary": "#745B64",
        "muted": "#9A838B",
        "accent": "#A83D5B",
        "accent_hover": "#8D304A",
        "accent_soft": "#F0D1DB",
        "accent_pale": "#FAE7ED",
        "error": "#B53B42",
        "on_accent": "#FFFFFF",
    },
    "midnight": {
        "label": "深夜蓝",
        "background": "#151A24",
        "sidebar": "#1C2431",
        "input": "#242E3E",
        "hover": "#2B374A",
        "divider": "#334157",
        "text": "#EFF4FF",
        "secondary": "#B8C4D8",
        "muted": "#8494AC",
        "accent": "#7CA7FF",
        "accent_hover": "#9AB9FF",
        "accent_soft": "#2C4168",
        "accent_pale": "#202F4A",
        "error": "#FF7A76",
        "on_accent": "#101722",
    },
}

APPEARANCE_PRESETS = [
    {"id": "light", "label": "清爽浅色", "theme": "light", "effect": "solid"},
    {"id": "warm", "label": "柔和暖色", "theme": "warm", "effect": "solid"},
    {"id": "cool", "label": "冷静蓝灰", "theme": "cool", "effect": "solid"},
    {"id": "mint", "label": "薄荷绿", "theme": "mint", "effect": "solid"},
    {"id": "rose", "label": "玫瑰粉", "theme": "rose", "effect": "solid"},
    {"id": "dark", "label": "深色哑光", "theme": "dark", "effect": "solid"},
    {"id": "midnight", "label": "深夜蓝", "theme": "midnight", "effect": "solid"},
    {"id": "warm-acrylic", "label": "暖色毛玻璃", "theme": "warm", "effect": "acrylic"},
    {"id": "cool-acrylic", "label": "冷色毛玻璃", "theme": "cool", "effect": "acrylic"},
    {"id": "dark-acrylic", "label": "深色毛玻璃", "theme": "dark", "effect": "acrylic"},
    {"id": "glass", "label": "清透玻璃", "theme": "light", "effect": "transparent"},
]

PRESET_BY_ID = {preset["id"]: preset for preset in APPEARANCE_PRESETS}

def _rgba(hex_color: str, alpha: int) -> str:
    value = hex_color.lstrip("#")
    red, green, blue = (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
    )
    return f"rgba({red}, {green}, {blue}, {alpha})"


def build_app_style(theme_name: str = "light", *, effect: str = "solid") -> str:
    colors = THEMES.get(theme_name, THEMES["light"])
    glass = effect in {"acrylic", "transparent"}
    if effect == "acrylic":
        alpha = (210, 220, 232, 230, 180, 220, 205)
    elif effect == "transparent":
        alpha = (145, 160, 175, 185, 165, 190, 165)
    else:
        alpha = (255, 255, 255, 255, 255, 255, 255)
    background = _rgba(colors["background"], alpha[0]) if glass else colors["background"]
    sidebar = _rgba(colors["sidebar"], alpha[1]) if glass else colors["sidebar"]
    input_color = _rgba(colors["input"], alpha[2]) if glass else colors["input"]
    hover = _rgba(colors["hover"], alpha[3]) if glass else colors["hover"]
    divider = _rgba(colors["divider"], alpha[4]) if glass else colors["divider"]
    accent_soft = (
        _rgba(colors["accent_soft"], alpha[5]) if glass else colors["accent_soft"]
    )
    accent_pale = (
        _rgba(colors["accent_pale"], alpha[6]) if glass else colors["accent_pale"]
    )
    window_background = "transparent" if glass else colors["background"]
    return f"""
* {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    font-size: 15px;
    color: {colors["text"]};
}}
QMainWindow, QWidget#Page {{
    background: {window_background};
}}
QWidget#Sidebar {{
    background: {sidebar};
}}
QWidget#TopBar, QWidget#EventBar {{
    background: {background};
}}
QLabel#RoomTitle {{
    font-size: 18px;
    font-weight: 600;
}}
QLabel#SectionTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {colors["secondary"]};
}}
QLabel#Secondary {{
    font-size: 13px;
    color: {colors["secondary"]};
}}
QLabel#Muted {{
    font-size: 12px;
    color: {colors["muted"]};
}}
QLabel#TrackTitle {{
    font-size: 24px;
    font-weight: 600;
}}
QLabel#StatusText {{
    font-size: 13px;
    color: {colors["secondary"]};
}}
QLabel#ErrorText {{
    font-size: 13px;
    color: {colors["error"]};
}}
QTextBrowser#Lyrics {{
    background: {colors["accent_pale"]};
    border: none;
    border-radius: 8px;
    padding: 14px;
    color: {colors["secondary"]};
    font-size: 14px;
}}
QLineEdit, QSpinBox, QComboBox {{
    background: {input_color};
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 14px;
    color: {colors["text"]};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    background: {colors["background"]};
    border: 1px solid {colors["accent"]};
}}
QPushButton {{
    background: {colors["background"]};
    border: 1px solid {divider};
    border-radius: 6px;
    padding: 7px 12px;
    font-size: 14px;
    color: {colors["text"]};
}}
QPushButton:hover {{
    background: {hover};
}}
QPushButton:focus {{
    border: 1px solid {colors["accent"]};
}}
QPushButton:disabled {{
    color: {colors["muted"]};
    background: transparent;
    border-color: {divider};
}}
QPushButton#ModeButton, QPushButton#CompactButton {{
    padding: 4px 8px;
    font-size: 13px;
}}
QPushButton#Primary {{
    background: {colors["accent"]};
    color: {colors["on_accent"]};
    border: none;
}}
QPushButton#Primary:hover {{
    background: {colors["accent_hover"]};
}}
QPushButton#Danger {{
    color: {colors["error"]};
    border-color: {colors["error"]};
}}
QPushButton#Danger:disabled {{
    color: {colors["muted"]};
    border-color: {divider};
}}
QPushButton#IconButton {{
    border: none;
    background: transparent;
    border-radius: 18px;
    padding: 6px;
}}
QPushButton#IconButton:hover {{
    background: {colors["hover"]};
}}
QListWidget {{
    background: {sidebar};
    border: none;
    outline: none;
    color: {colors["text"]};
}}
QListWidget::item {{
    min-height: 46px;
    padding: 5px 10px;
    border-radius: 6px;
}}
QListWidget::item:hover {{
    background: {hover};
}}
QListWidget::item:selected {{
    background: {accent_soft};
    color: {colors["text"]};
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: {divider};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {colors["accent"]};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 12px;
    height: 12px;
    margin: -4px 0;
    background: {colors["background"]};
    border: 2px solid {colors["accent"]};
    border-radius: 6px;
}}
QSplitter::handle {{
    background: {divider};
}}
QSplitter::handle:hover {{
    background: {colors["accent"]};
}}QFrame#Divider {{
    background: {divider};
    max-height: 1px;
}}
QWidget#Panel {{
    background: {background};
}}
QDialog {{
    background: {colors["background"]};
}}
QMenu {{
    background: {colors["background"]};
    border: 1px solid {divider};
    padding: 4px;
}}
QMenu::item {{
    padding: 7px 22px;
    border-radius: 4px;
    color: {colors["text"]};
}}
QMenu::item:selected {{
    background: {hover};
}}

"""
