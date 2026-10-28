import struct
import unittest
from pathlib import Path

from PySide6.QtGui import QImage


class IconAssetTests(unittest.TestCase):
    def test_application_icon_assets_are_valid(self) -> None:
        assets = (
            Path(__file__).parents[1]
            / "src"
            / "listen_together"
            / "assets"
        )
        image = QImage(str(assets / "app-icon.png"))
        self.assertFalse(image.isNull())
        self.assertEqual((image.width(), image.height()), (256, 256))

        icon_data = (assets / "app-icon.ico").read_bytes()
        self.assertEqual(struct.unpack("<HHH", icon_data[:6]), (0, 1, 1))


if __name__ == "__main__":
    unittest.main()
