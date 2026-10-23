import argparse
import time
from pathlib import Path

import mutagen
from listen_together.player.vlc_backend import vlc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    path = Path(args.path).resolve()

    audio = mutagen.File(path)
    print("mutagen_type", type(audio).__name__ if audio else None)
    print("mutagen_length", getattr(getattr(audio, "info", None), "length", None))
    print("size", path.stat().st_size)
    print("header", path.read_bytes()[:32].hex())

    instance = vlc.Instance("--no-video", "--quiet", "--aout=dummy")
    media = instance.media_new(str(path))
    parse_result = media.parse()
    print("parse_result", parse_result)
    print("parsed_status", media.get_parsed_status())
    print("duration_before_play", media.get_duration())

    player = instance.media_player_new()
    player.set_media(media)
    print("play_result", player.play())
    for _ in range(80):
        time.sleep(0.05)
        print(
            "state",
            player.get_state(),
            "time",
            player.get_time(),
            "length",
            player.get_length(),
        )
        if player.get_time() > 0:
            break
    player.stop()
    player.release()
    media.release()
    instance.release()


if __name__ == "__main__":
    main()
