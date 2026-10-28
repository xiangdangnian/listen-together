import ctypes
import sys

from PySide6.QtWidgets import QWidget


class _Margins(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_int),
        ("right", ctypes.c_int),
        ("top", ctypes.c_int),
        ("bottom", ctypes.c_int),
    ]


def apply_windows_glass(window: QWidget, effect: str) -> bool:
    if sys.platform != "win32":
        return False
    hwnd = int(window.winId())
    try:
        dwmapi = ctypes.windll.dwmapi
        backdrop_type = 3 if effect == "acrylic" else 1
        result = dwmapi.DwmSetWindowAttribute(
            hwnd,
            38,
            ctypes.byref(ctypes.c_int(backdrop_type)),
            ctypes.sizeof(ctypes.c_int),
        )
        if effect == "acrylic":
            margins = _Margins(-1, -1, -1, -1)
            dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        return result == 0
    except (AttributeError, OSError):
        return False

def apply_windows_titlebar(
    window: QWidget,
    *,
    background: str,
    foreground: str,
    dark: bool,
) -> bool:
    if sys.platform != "win32":
        return False
    hwnd = int(window.winId())
    try:
        dwmapi = ctypes.windll.dwmapi
        dark_value = ctypes.c_int(1 if dark else 0)
        result = dwmapi.DwmSetWindowAttribute(
            hwnd,
            20,
            ctypes.byref(dark_value),
            ctypes.sizeof(dark_value),
        )
        caption = _colorref(background)
        text_color = _colorref(foreground)
        for attribute, value in ((35, caption), (36, text_color)):
            color = ctypes.c_int(value)
            dwmapi.DwmSetWindowAttribute(
                hwnd,
                attribute,
                ctypes.byref(color),
                ctypes.sizeof(color),
            )
        return result == 0
    except (AttributeError, OSError):
        return False


def _colorref(hex_color: str) -> int:
    value = hex_color.lstrip("#")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)