import io
from unittest.mock import patch

import pytest

from flock.bus.resp import Redis, ResponseError


class FakeSocket:
    def __init__(self, replies):
        self.reader = io.BytesIO(replies)
        self.requests = []

    def makefile(self, mode):
        assert mode == "rb"
        return self.reader

    def sendall(self, request):
        self.requests.append(request)


def client(replies):
    sock = FakeSocket(replies)
    with patch("flock.bus.resp.socket.create_connection", return_value=sock):
        return Redis.from_url("redis://127.0.0.1:6379/0"), sock


def test_reply_types_match_redis_py_bytes_mode():
    r, _ = client(b"$5\r\nvalue\r\n$-1\r\n:3\r\n*2\r\n$3\r\nkey\r\n$5\r\nvalue\r\n*-1\r\n")
    assert r.get("one") == b"value"
    assert r.get("missing") is None
    assert r.llen("items") == 3
    assert r.hgetall("hash") == {b"key": b"value"}
    assert r.blpop("empty", timeout=1) is None


def test_blpop_returns_bytes_key_and_value():
    r, _ = client(b"*2\r\n$7\r\ningress\r\n$3\r\nraw\r\n")
    assert r.blpop("ingress", timeout=1) == [b"ingress", b"raw"]


def test_commands_are_one_resp_request_and_xadd_shape_is_exact():
    r, sock = client(b":2\r\n$3\r\n1-0\r\n")
    assert r.rpush("queue", "hello") == 2
    assert sock.requests[0] == b"*3\r\n$5\r\nRPUSH\r\n$5\r\nqueue\r\n$5\r\nhello\r\n"
    assert r.xadd("feed", {"event": "{}"}, maxlen=1000, approximate=True) == b"1-0"
    assert b"MAXLEN\r\n$1\r\n~\r\n$4\r\n1000\r\n" in sock.requests[1]


def test_error_reply_raises():
    r, _ = client(b"-WRONGTYPE bad key\r\n")
    with pytest.raises(ResponseError, match="WRONGTYPE bad key"):
        r.get("bad")


def test_url_auth_and_database_are_selected():
    sock = FakeSocket(b"+OK\r\n+OK\r\n")
    with patch("flock.bus.resp.socket.create_connection", return_value=sock):
        Redis.from_url("redis://:p%40ss@redis.example:6380/2")
    assert b"AUTH" in sock.requests[0] and b"p@ss" in sock.requests[0]
    assert b"SELECT" in sock.requests[1] and b"2" in sock.requests[1]
