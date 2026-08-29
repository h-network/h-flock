"""Tail log lines written inside agent windows into container stdout."""

import json
from pathlib import Path

from flock.bus.keys import prefix
from flock.bus.logging import log_record, mirror


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
                            "switch",
                            "window_log_decode_error",
                            reason=f"invalid UTF-8 at byte {committed + exc.start}",
                            byte_count=len(raw),
                        )
                        committed = source.tell()
                        continue
                    try:
                        record = json.loads(line)
                    except (TypeError, json.JSONDecodeError):
                        record = None
                    if isinstance(record, dict):
                        # A current log_record already carries the process label.
                        # Legacy/custom pane writers do not. Preserve an explicit
                        # writer byte-for-byte in meaning; only fill the absence.
                        if "writer" not in record:
                            agent = (
                                record.get("source")
                                or record.get("agent")
                                or record.get("destination")
                                or "unknown"
                            )
                            record["writer"] = f"window:{agent}"
                            line = json.dumps(record, separators=(",", ":"))
                    print(line, flush=True)
                    # ⚠ THE ORIGIN RECORD OF EVERY AGENT SEND COMES THROUGH HERE.
                    # `office` runs in a pane and is QUIET, so its `sent` never
                    # touches stdout directly — it lands in the window file and
                    # reaches the log only when this re-emits it. Without this
                    # call the durable evidence has `popped` through `opened` and
                    # no `sent`, which reads exactly like an envelope the bus
                    # invented. Measured on a live tenant 2026-08-22: five of six
                    # stages in the file, `sent` count 0.
                    mirror(line)
                    committed = source.tell()
            self.r.set(self.offset_key, committed)
            current_size = self.path.stat().st_size
            if current_size > self.max_bytes and committed == current_size:
                self.path.write_bytes(b"")
                self.r.set(self.offset_key, 0)
                log_record("switch", "window_log_truncated", byte_count=current_size)
        except (OSError, TypeError, ValueError):
            # A missing/rotating file is an absent observation, never a switch
            # failure. The next existing pass tries again from the same offset.
            return
