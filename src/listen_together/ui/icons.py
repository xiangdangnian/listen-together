from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


_ICONS = {
    "volume-2": (
        '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 '
        '7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 '
        '0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 '
        '0 0 0 11 19.298z"/>'
        '<path d="M16 9a5 5 0 0 1 0 6"/>'
        '<path d="M19.364 18.364a9 9 0 0 0 0-12.728"/>'
    ),
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "locate-fixed": (
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M12 2v3"/><path d="M12 19v3"/>'
        '<path d="M2 12h3"/><path d="M19 12h3"/>'
    ),
    "list": (
        '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/>'
        '<path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>'
    ),
    "repeat-2": (
        '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/>'
        '<path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>'
    ),
    "shuffle": (
        '<path d="m18 14 4 4-4 4"/><path d="m18 2 4 4-4 4"/>'
        '<path d="M2 18h1.973a4 4 0 0 0 3.3-1.7l5.454-8.6a4 4 0 0 1 3.3-1.7H22"/>'
        '<path d="M2 6h1.972a4 4 0 0 1 3.6 2.2"/>'
        '<path d="M22 18h-6.041a4 4 0 0 1-3.3-1.8l-.359-.45"/>'
    ),
}


def lucide_pixmap(
    name: str,
    *,
    color: str,
    size: int = 20,
    scale: int = 2,
) -> QPixmap:
    body = _ICONS.get(name, _ICONS["volume-2"])
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return pixmap


def lucide_icon(name: str, *, color: str, size: int = 20) -> QIcon:
    return QIcon(lucide_pixmap(name, color=color, size=size))

