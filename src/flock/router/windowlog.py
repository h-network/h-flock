"""Tail log lines written inside agent windows into container stdout."""

from pathlib import Path

from flock.bus import prefix


class WindowLogTailer:
    def __init__(
        self,
        r,
        *,
        pod: str,
        tenant: str,
        path: str | Path = "/home/ubuntu/.flock/window.log.jsonl",
    ):
        self.r = r
        self.path = Path(path)
        self.offset_key = prefix(pod, tenant, resource="window.log.offset")

    def poll(self) -> None:
        try:
            raw_offset = self.r.get(self.offset_key)
            offset = int(raw_offset or 0)
            size = self.path.stat().st_size
            if offset > size:
                offset = 0
            with self.path.open("rb") as source:
                source.seek(offset)
                committed = offset
                while raw := source.readline():
                    if not raw.endswith(b"\n"):
                        break
                    print(raw.decode("utf-8").rstrip("\n"), flush=True)
                    committed = source.tell()
            self.r.set(self.offset_key, committed)
        except (OSError, UnicodeDecodeError, TypeError, ValueError):
            # A missing/rotating file is an absent observation, never a router
            # failure. The next existing pass tries again from the same offset.
            return
