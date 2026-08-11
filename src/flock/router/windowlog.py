"""Tail log lines written inside agent windows into container stdout."""

from pathlib import Path

from flock.bus import log_record, prefix


class WindowLogTailer:
    def __init__(
        self,
        r,
        *,
        pod: str,
        tenant: str,
        path: str | Path = "/home/ubuntu/.flock/window.log.jsonl",
        max_bytes: int = 8 * 1024 * 1024,
    ):
        if max_bytes < 1:
            raise ValueError("window log cap must be positive")
        self.r = r
        self.path = Path(path)
        self.max_bytes = max_bytes
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
                    try:
                        line = raw.decode("utf-8").rstrip("\n")
                    except UnicodeDecodeError as exc:
                        # A complete poisoned line must not pin the tenant offset
                        # forever. Record and skip exactly that line; later valid
                        # records and size-based truncation can then progress.
                        log_record(
                            "router",
                            "window_log_decode_error",
                            reason=f"invalid UTF-8 at byte {committed + exc.start}",
                            byte_count=len(raw),
                        )
                        committed = source.tell()
                        continue
                    print(line, flush=True)
                    committed = source.tell()
            self.r.set(self.offset_key, committed)
            current_size = self.path.stat().st_size
            if current_size > self.max_bytes and committed == current_size:
                self.path.write_bytes(b"")
                self.r.set(self.offset_key, 0)
                log_record("router", "window_log_truncated", byte_count=current_size)
        except (OSError, TypeError, ValueError):
            # A missing/rotating file is an absent observation, never a router
            # failure. The next existing pass tries again from the same offset.
            return
