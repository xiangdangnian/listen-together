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


if __name__ == "__main__":
    unittest.main()
