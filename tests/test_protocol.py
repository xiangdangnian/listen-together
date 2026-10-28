import socket
import unittest

from listen_together.net.protocol import (
    auth_response,
    receive_json,
    send_json,
)


class ProtocolTests(unittest.TestCase):
    def test_json_frame_round_trip(self) -> None:
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        message = {"type": "hello", "message": "音乐"}

        send_json(left, message)

        self.assertEqual(receive_json(right), message)

    def test_large_snapshot_frame_round_trip(self) -> None:
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        message = {"type": "snapshot", "data": "歌" * 100_000}

        send_json(left, message)

        self.assertEqual(receive_json(right), message)
    def test_auth_response_is_stable(self) -> None:
        first = auth_response("123456", "nonce-1")
        second = auth_response("123456", "nonce-1")

        self.assertEqual(first, second)
        self.assertNotEqual(first, auth_response("654321", "nonce-1"))
        self.assertEqual(len(first), 64)


if __name__ == "__main__":
    unittest.main()
