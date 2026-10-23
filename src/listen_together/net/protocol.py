import hashlib
import hmac
import json
import socket
import struct
from typing import Any


MAX_JSON_FRAME = 64 * 1024


def auth_response(passphrase: str, nonce: str) -> str:
    return hmac.new(
        passphrase.encode("utf-8"),
        nonce.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def send_json(sock: socket.socket, payload: dict[str, Any]) -> None:
    data = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(data) > MAX_JSON_FRAME:
        raise ValueError("JSON frame is too large.")
    sock.sendall(struct.pack(">I", len(data)) + data)


def receive_json(sock: socket.socket) -> dict[str, Any]:
    header = receive_exact(sock, 4)
    length = struct.unpack(">I", header)[0]
    if length <= 0 or length > MAX_JSON_FRAME:
        raise ValueError("Invalid JSON frame length.")
    data = receive_exact(sock, length)
    parsed = json.loads(data.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("Protocol payload must be a JSON object.")
    return parsed


def receive_exact(sock: socket.socket, byte_count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < byte_count:
        chunk = sock.recv(byte_count - len(chunks))
        if not chunk:
            raise ConnectionError("Connection closed while receiving data.")
        chunks.extend(chunk)
    return bytes(chunks)


def send_file(sock: socket.socket, path, *, progress=None) -> None:
    total = path.stat().st_size
    sent = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            sock.sendall(chunk)
            sent += len(chunk)
            if progress is not None:
                progress(sent, total)


def receive_file(
    sock: socket.socket,
    destination,
    *,
    byte_count: int,
    progress=None,
) -> None:
    received = 0
    with destination.open("wb") as output:
        while received < byte_count:
            chunk = sock.recv(min(1024 * 1024, byte_count - received))
            if not chunk:
                raise ConnectionError("Connection closed during file transfer.")
            output.write(chunk)
            received += len(chunk)
            if progress is not None:
                progress(received, byte_count)
