import unittest

from listen_together.ui.theme import APPEARANCE_PRESETS, THEMES, build_app_style


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def _luminance(value: str) -> float:
    channels = []
    for channel in _rgb(value):
        normalized = channel / 255
        channels.append(
            normalized / 12.92
            if normalized <= 0.04045
            else ((normalized + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(first: str, second: str) -> float:
    high = max(_luminance(first), _luminance(second))
    low = min(_luminance(first), _luminance(second))
    return (high + 0.05) / (low + 0.05)


class ThemeTests(unittest.TestCase):
    def test_presets_map_to_valid_themes_and_effects(self) -> None:
        ids = [preset["id"] for preset in APPEARANCE_PRESETS]
        self.assertEqual(len(ids), len(set(ids)))
        for preset in APPEARANCE_PRESETS:
            self.assertIn(preset["theme"], THEMES)
            self.assertIn(preset["effect"], {"solid", "acrylic", "transparent"})

    def test_every_theme_has_readable_contrast(self) -> None:
        for name, colors in THEMES.items():
            with self.subTest(theme=name):
                self.assertGreaterEqual(_contrast(colors["text"], colors["background"]), 7.0)
                self.assertGreaterEqual(
                    _contrast(colors["secondary"], colors["background"]),
                    4.5,
                )
                self.assertGreaterEqual(_contrast(colors["muted"], colors["background"]), 3.0)
                self.assertGreaterEqual(
                    _contrast(colors["on_accent"], colors["accent"]),
                    4.0,
                )

    def test_player_panel_selector_matches_widget(self) -> None:
        style = build_app_style("dark")
        self.assertIn("QWidget#Panel", style)
        self.assertNotIn("QFrame#Panel", style)