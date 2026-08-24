import io
import ast
from pathlib import Path
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


def test_eval_is_one_resp_request_with_keys_before_arguments():
    r, sock = client(b":1\r\n")
    assert r.eval("return redis.call('SET', KEYS[1], ARGV[1])", 1, "cause", "corr-1") == 1
    assert sock.requests[0] == (
        b"*5\r\n$4\r\nEVAL\r\n"
        b"$42\r\nreturn redis.call('SET', KEYS[1], ARGV[1])\r\n"
        b"$1\r\n1\r\n$5\r\ncause\r\n$6\r\ncorr-1\r\n"
    )


def test_resp_doubles_do_not_expose_commands_missing_from_production_client():
    """Structural invariant: marked RESP doubles cannot outrun the real client."""
    production = {
        name for name, value in vars(Redis).items()
        if callable(value) and not name.startswith("_")
    }
    doubles = []
    violations = []
    for path in sorted((Path(__file__).parent).glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            marked = any(
                isinstance(item, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "__resp_double__" for target in item.targets)
                and isinstance(item.value, ast.Constant)
                and item.value.value is True
                for item in node.body
            )
            if not marked:
                continue
            doubles.append(f"{path.name}:{node.name}")
            exposed = {
                item.name for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not item.name.startswith("_")
            }
            for method in sorted(exposed - production):
                violations.append(f"{path.name}:{node.name}.{method}")

    assert len(doubles) >= 2, f"Expected at least 2 marked RESP doubles, found {doubles}"
    assert not violations, "RESP test doubles exceed production Redis: " + ", ".join(violations)


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


def test_xrange_parses_stream_entries_with_field_dict():
    payload = b'{"agent":"bus","input":100}'
    resp_reply = (
        b"*1\r\n"
        b"*2\r\n"
        b"$3\r\n1-0\r\n"
        b"*2\r\n"
        b"$5\r\nusage\r\n"
        + f"${len(payload)}\r\n".encode()
        + payload
        + b"\r\n"
    )
    r, sock = client(resp_reply)
    entries = r.xrange("usage", min="-", max="+")
    assert entries == [(b"1-0", {b"usage": b'{"agent":"bus","input":100}'})]
    assert sock.requests[0] == b"*4\r\n$6\r\nXRANGE\r\n$5\r\nusage\r\n$1\r\n-\r\n$1\r\n+\r\n"
