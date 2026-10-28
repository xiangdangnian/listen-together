import json
import unittest

from listen_together.domain.room import HostRoom


class HostRoomTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now_us = 1_000_000
        self.room = HostRoom(
            room_id="room-1",
            room_name="Test Room",
            now_us=lambda: self.now_us,
        )
        self.room.add_member("Host", member_id="host", is_host=True)

    def test_current_track_waits_for_every_online_member(self) -> None:
        self.room.add_member("Guest", member_id="guest")
        self.room.add_track(
            member_id="host",
            track_id="sha256:a",
            title="Track A",
            artist="Artist",
            duration_ms=180_000,
            size_bytes=1_024,
        )

        self.room.mark_media_ready("host", "sha256:a")
        self.room.tick()
        self.assertFalse(self.room.snapshot()["playback"]["playing"])

        self.room.mark_media_ready("guest", "sha256:a")
        self.room.tick()
        self.assertTrue(self.room.snapshot()["playback"]["playing"])

    def test_late_member_pauses_and_resumes_at_current_position(self) -> None:
        self.room.add_track(
            member_id="host",
            track_id="sha256:a",
            title="Track A",
            artist="Artist",
            duration_ms=180_000,
            size_bytes=1_024,
        )
        self.room.mark_media_ready("host", "sha256:a")
        self.room.tick()
        self.now_us = self.room.snapshot()["playback"]["anchor_host_us"] + 2_000_000

        self.room.add_member("Guest", member_id="guest")
        self.assertFalse(self.room.snapshot()["playback"]["playing"])

        self.room.mark_media_ready("guest", "sha256:a")
        self.room.tick()
        playback = self.room.snapshot()["playback"]
        self.assertTrue(playback["playing"])
        self.assertGreaterEqual(playback["anchor_position_ms"], 2_000)

    def test_guest_cannot_remove_another_members_track(self) -> None:
        self.room.add_member("Guest", member_id="guest")
        track = self.room.add_track(
            member_id="host",
            track_id="sha256:a",
            title="Track A",
            artist="Artist",
            duration_ms=180_000,
            size_bytes=1_024,
        )

        self.assertFalse(self.room.remove_track(track.queue_id, actor_id="guest"))
        self.assertTrue(self.room.remove_track(track.queue_id, actor_id="host"))

    def test_batch_remove_updates_revision_once(self) -> None:
        first = self.room.add_track(
            member_id="host",
            track_id="sha256:a",
            title="Track A",
            artist="Artist",
            duration_ms=180_000,
            size_bytes=1_024,
        )
        second = self.room.add_track(
            member_id="host",
            track_id="sha256:b",
            title="Track B",
            artist="Artist",
            duration_ms=180_000,
            size_bytes=1_024,
        )
        third = self.room.add_track(
            member_id="host",
            track_id="sha256:c",
            title="Track C",
            artist="Artist",
            duration_ms=180_000,
            size_bytes=1_024,
        )
        revision = self.room.snapshot()["queue_revision"]

        removed, denied = self.room.remove_tracks(
            [first.queue_id, second.queue_id],
            actor_id="host",
        )

        self.assertEqual(removed, [first.queue_id, second.queue_id])
        self.assertEqual(denied, [])
        self.assertEqual(self.room.snapshot()["queue_revision"], revision + 1)
        self.assertEqual(self.room.current_track.queue_id, third.queue_id)

    def test_snapshot_only_carries_current_lyrics(self) -> None:
        self.room.add_track(
            member_id="host",
            track_id="sha256:a",
            title="Track A",
            artist="Artist",
            duration_ms=180_000,
            size_bytes=1_024,
            lyrics="第一首歌词" * 1_000,
            lyrics_lrc="[00:01.00]第一首歌词\n" * 500,
        )
        self.room.add_track(
            member_id="host",
            track_id="sha256:b",
            title="Track B",
            artist="Artist",
            duration_ms=180_000,
            size_bytes=1_024,
            lyrics="第二首歌词" * 1_000,
            lyrics_lrc="[00:01.00]第二首歌词\n" * 500,
        )

        queue = self.room.snapshot()["queue"]

        self.assertIn("lyrics", queue[0])
        self.assertIn("lyrics_lrc", queue[0])
        self.assertNotIn("lyrics", queue[1])
        self.assertNotIn("lyrics_lrc", queue[1])

    def test_five_hundred_tracks_fit_network_frame(self) -> None:
        for index in range(500):
            self.room.add_track(
                member_id="host",
                track_id=f"sha256:{index:064x}",
                title=f"Track {index}",
                artist="Artist",
                duration_ms=180_000,
                size_bytes=1_024,
                lyrics="歌词" * 500,
                lyrics_lrc="[00:01.00]歌词\n" * 100,
            )

        payload = json.dumps(
            {"type": "snapshot", "snapshot": self.room.snapshot()},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        self.assertLess(len(payload), 2 * 1024 * 1024)
    def test_single_track_loop_starts_a_new_playback_run(self) -> None:
        track = self.room.add_track(
            member_id="host",
            track_id="sha256:a",
            title="Track A",
            artist="Artist",
            duration_ms=1_000,
            size_bytes=1_024,
        )
        self.room.set_playback_mode("loop")
        self.room.mark_media_ready("host", track.track_id)
        self.room.tick()
        first = self.room.snapshot()["playback"]
        self.assertTrue(first["playing"])

        self.now_us = first["anchor_host_us"] + 1_100_000
        self.room.tick()
        second = self.room.snapshot()["playback"]
        self.assertEqual(second["track_id"], track.track_id)
        self.assertGreater(second["run_id"], first["run_id"])
        self.assertFalse(second["playing"])

        self.room.mark_media_ready("host", track.track_id)
        self.room.tick()
        third = self.room.snapshot()["playback"]
        self.assertTrue(third["playing"])
        self.assertEqual(third["run_id"], second["run_id"])
    def test_loop_mode_wraps_after_last_track(self) -> None:
        first = self.room.add_track(
            member_id="host",
            track_id="sha256:a",
            title="Track A",
            artist="Artist",
            duration_ms=180_000,
            size_bytes=1_024,
        )
        second = self.room.add_track(
            member_id="host",
            track_id="sha256:b",
            title="Track B",
            artist="Artist",
            duration_ms=180_000,
            size_bytes=1_024,
        )
        self.room.set_playback_mode("loop")
        self.room.play_queue_item(second.queue_id)

        self.room.next()

        self.assertEqual(self.room.current_track.track_id, first.track_id)
        self.assertEqual(self.room.snapshot()["playback_mode"], "loop")

    def test_shuffle_mode_chooses_a_different_track(self) -> None:
        self.room.add_track(
            member_id="host",
            track_id="sha256:a",
            title="Track A",
            artist="Artist",
            duration_ms=180_000,
            size_bytes=1_024,
        )
        second = self.room.add_track(
            member_id="host",
            track_id="sha256:b",
            title="Track B",
            artist="Artist",
            duration_ms=180_000,
            size_bytes=1_024,
        )
        self.room.set_playback_mode("shuffle")

        self.room.next()

        self.assertEqual(self.room.current_track.track_id, second.track_id)


    def test_duplicate_track_is_detected_in_queue(self) -> None:
        self.room.add_track(
            member_id="host",
            track_id="sha256:a",
            title="Track A",
            artist="Artist",
            duration_ms=180_000,
            size_bytes=1_024,
        )
        self.assertTrue(self.room.has_track("sha256:a"))
        self.assertFalse(self.room.has_track("sha256:b"))

    def test_listening_time_counts_only_active_playback(self) -> None:
        self.room.add_track(
            member_id="host",
            track_id="sha256:a",
            title="Track A",
            artist="Artist",
            duration_ms=180_000,
            size_bytes=1_024,
        )
        self.room.mark_media_ready("host", "sha256:a")
        self.room.tick()
        start_at = self.room.snapshot()["playback"]["anchor_host_us"]
        self.now_us = start_at + 2_000_000
        self.room.tick()
        self.assertEqual(self.room.snapshot()["listening_ms"], 2_000)

        self.now_us += 2_000_000
        self.room.pause()
        self.now_us += 5_000_000
        self.room.tick()
        self.assertEqual(self.room.snapshot()["listening_ms"], 4_000)

    def test_sequential_finish_removes_track_and_previous_restores_it(self) -> None:
        first = self.room.add_track(
            member_id="host",
            track_id="sha256:a",
            title="Track A",
            artist="Artist",
            duration_ms=1_000,
            size_bytes=1_024,
        )
        second = self.room.add_track(
            member_id="host",
            track_id="sha256:b",
            title="Track B",
            artist="Artist",
            duration_ms=180_000,
            size_bytes=1_024,
        )
        self.room.mark_media_ready("host", "sha256:a")
        self.room.tick()
        start_at = self.room.snapshot()["playback"]["anchor_host_us"]
        self.now_us = start_at + 1_100_000
        self.room.tick()

        self.assertEqual([item.queue_id for item in self.room._queue], [second.queue_id])
        self.assertEqual(self.room.current_track.queue_id, second.queue_id)
        self.assertEqual(self.room.snapshot()["history_track_ids"], [first.track_id])

        self.room.previous()
        self.assertEqual(self.room.current_track.queue_id, first.queue_id)
        self.assertEqual(self.room.snapshot()["queue"][0]["queue_id"], first.queue_id)
if __name__ == "__main__":
    unittest.main()
