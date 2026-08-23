"""Minimal synchronous RESP2 client for one-shot office processes."""

import socket
from urllib.parse import unquote, urlparse


class ResponseError(RuntimeError):
    pass


def _bytes(value) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode()
    return str(value).encode()


class Redis:
    """One connection, bytes responses, and only the one-shot command surface."""

    def __init__(self, host: str, port: int, *, password: str | None = None, db: int = 0):
        self._socket = socket.create_connection((host, port))
        self._reader = self._socket.makefile("rb")
        if password is not None:
            self._command("AUTH", password)
        if db:
            self._command("SELECT", db)

    @classmethod
    def from_url(cls, url: str):
        parsed = urlparse(url)
        if parsed.scheme != "redis" or parsed.hostname is None:
            raise ValueError("RESP client requires a redis:// URL")
        db_text = parsed.path.lstrip("/")
        return cls(
            parsed.hostname,
            parsed.port or 6379,
            password=unquote(parsed.password) if parsed.password is not None else None,
            db=int(db_text) if db_text else 0,
        )

    def _read(self):
        marker = self._reader.read(1)
        if not marker:
            raise ConnectionError("Redis closed the connection")
        line = self._reader.readline()
        if not line.endswith(b"\r\n"):
            raise ConnectionError("truncated RESP reply")
        value = line[:-2]
        if marker == b"+":
            return value
        if marker == b"-":
            raise ResponseError(value.decode("utf-8", "replace"))
        if marker == b":":
            return int(value)
        if marker == b"$":
            length = int(value)
            if length == -1:
                return None
            payload = self._reader.read(length)
            if len(payload) != length or self._reader.read(2) != b"\r\n":
                raise ConnectionError("truncated RESP bulk reply")
            return payload
        if marker == b"*":
            count = int(value)
            if count == -1:
                return None
            return [self._read() for _ in range(count)]
        raise ConnectionError(f"unknown RESP reply marker: {marker!r}")

    def _command(self, *parts):
        encoded = [_bytes(part) for part in parts]
        request = [f"*{len(encoded)}\r\n".encode()]
        for part in encoded:
            request.extend((f"${len(part)}\r\n".encode(), part, b"\r\n"))
        self._socket.sendall(b"".join(request))
        return self._read()

    def rpush(self, key, *values): return self._command("RPUSH", key, *values)
    def lrange(self, key, start, stop): return self._command("LRANGE", key, start, stop)
    def get(self, key): return self._command("GET", key)

    def xadd(self, key, fields, *, maxlen=None, approximate=True):
        parts = ["XADD", key]
        if maxlen is not None:
            parts.extend(("MAXLEN", "~" if approximate else "=", maxlen))
        parts.append("*")
        for field, value in fields.items():
            parts.extend((field, value))
        return self._command(*parts)

    def xrange(self, key, min="-", max="+", count=None):
        parts = ["XRANGE", key, min, max]
        if count is not None:
            parts.extend(("COUNT", count))
        raw = self._command(*parts)
        if not raw:
            return []
        result = []
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                entry_id, fields_list = item[0], item[1]
                if isinstance(fields_list, (list, tuple)):
                    fields_dict = dict(zip(fields_list[::2], fields_list[1::2]))
                    result.append((entry_id, fields_dict))
                elif isinstance(fields_list, dict):
                    result.append((entry_id, fields_list))
                else:
                    result.append((entry_id, fields_list))
            else:
                result.append(item)
        return result

    def xrevrange(self, key, max="+", min="-", count=None):
        parts = ["XREVRANGE", key, max, min]
        if count is not None:
            parts.extend(("COUNT", count))
        raw = self._command(*parts)
        if not raw:
            return []
        result = []
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                entry_id, fields_list = item[0], item[1]
                if isinstance(fields_list, (list, tuple)):
                    fields_dict = dict(zip(fields_list[::2], fields_list[1::2]))
                    result.append((entry_id, fields_dict))
                elif isinstance(fields_list, dict):
                    result.append((entry_id, fields_list))
                else:
                    result.append((entry_id, fields_list))
            else:
                result.append(item)
        return result

    def xdel(self, key, *ids):
        return self._command("XDEL", key, *ids)

    def xlen(self, key): return self._command("XLEN", key)

    def hgetall(self, key):
        values = self._command("HGETALL", key)
        return dict(zip(values[::2], values[1::2]))

    def hget(self, key, field): return self._command("HGET", key, field)
    def hdel(self, key, *fields): return self._command("HDEL", key, *fields)

    def blpop(self, keys, timeout=0):
        if isinstance(keys, (str, bytes)):
            keys = [keys]
        return self._command("BLPOP", *keys, timeout)

    def lrem(self, key, count, value): return self._command("LREM", key, count, value)
    def lpop(self, key): return self._command("LPOP", key)
    def llen(self, key): return self._command("LLEN", key)
    def hsetnx(self, key, field, value): return self._command("HSETNX", key, field, value)
    def hkeys(self, key): return self._command("HKEYS", key)
    def hexists(self, key, field): return self._command("HEXISTS", key, field)
    def smembers(self, key): return self._command("SMEMBERS", key)
    def delete(self, *keys): return self._command("DEL", *keys)

    # Control is delivered by the same one-shot port and overwrites desired
    # state. These two calls are therefore part of its measured path even though
    # the Build 48 inventory omitted them.
    def set(self, key, value): return self._command("SET", key, value)
    def hset(self, key, field, value): return self._command("HSET", key, field, value)
