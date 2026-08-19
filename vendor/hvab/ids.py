"""Small UUIDv7 generator for Python versions before uuid.uuid7()."""

import secrets
import threading
import time
import uuid


_lock = threading.Lock()
_last_ms = -1
_sequence = 0


def uuid7() -> uuid.UUID:
    """Return a time-ordered RFC 9562 UUIDv7."""
    global _last_ms, _sequence
    now_ms = time.time_ns() // 1_000_000
    with _lock:
        if now_ms == _last_ms:
            _sequence = (_sequence + 1) & 0xFFF
            if _sequence == 0:
                while now_ms <= _last_ms:
                    now_ms = time.time_ns() // 1_000_000
        else:
            _sequence = secrets.randbits(12)
        _last_ms = now_ms
        random_b = secrets.randbits(62)
    value = (now_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= _sequence << 64
    value |= 0b10 << 62
    value |= random_b
    return uuid.UUID(int=value)
