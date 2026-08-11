"""Connection-string construction shared with the container boot path."""

from urllib.parse import quote


def local_redis_url(password: str) -> str:
    """Build the loopback Redis URL without treating password bytes as URL syntax."""
    return f"redis://:{quote(password, safe='')}@127.0.0.1:6379/0"
