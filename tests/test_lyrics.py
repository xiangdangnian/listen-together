import unittest

from listen_together.library.lyrics import parse_lrc, timed_lyric_index


class LyricsTests(unittest.TestCase):
    def test_lrc_timestamps_are_parsed_and_selected(self) -> None:
        lines = parse_lrc("[00:01.00]第一行\n[00:03.50]第二行\n")

        self.assertEqual([line.time_ms for line in lines], [1_000, 3_500])
        self.assertEqual(timed_lyric_index(lines, 2_000), 0)
        self.assertEqual(timed_lyric_index(lines, 3_600), 1)


if __name__ == "__main__":
    unittest.main()
