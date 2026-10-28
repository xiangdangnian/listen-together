import argparse
import struct
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--assets", required=True)
    args = parser.parse_args()

    source = QImage(args.source)
    if source.isNull():
        raise RuntimeError("Could not load the icon source image.")
    side = min(source.width(), source.height())
    left = (source.width() - side) // 2
    top = (source.height() - side) // 2
    square = source.copy(left, top, side, side).scaled(
        256,
        256,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    assets = Path(args.assets)
    assets.mkdir(parents=True, exist_ok=True)
    png_path = assets / "app-icon.png"
    ico_path = assets / "app-icon.ico"
    if not square.save(str(png_path), "PNG"):
        raise RuntimeError("Could not save PNG icon.")

    payload = png_path.read_bytes()
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack(
        "<BBBBHHII",
        0,
        0,
        0,
        0,
        1,
        32,
        len(payload),
        22,
    )
    ico_path.write_bytes(header + entry + payload)
    print(png_path)
    print(ico_path)


if __name__ == "__main__":
    main()
