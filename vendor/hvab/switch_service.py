"""Container entrypoint for one domain switch."""

import os
import signal

import redis

from .events import EventSink
from .keys import Keys
from .queue import SwitchQueueAccess
from .switch import Switch, SwitchService
from .table import ForwardingTable


def _redis_url() -> str:
    secret = os.environ.get("REDIS_URL_FILE")
    if secret:
        with open(secret, encoding="utf-8") as stream:
            return stream.read().strip()
    return os.environ["REDIS_URL"]


def main() -> None:
    pod = os.environ["POD"]
    domain = os.environ["DOMAIN"]
    keys = Keys(pod, domain)
    r = redis.Redis.from_url(_redis_url())
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with EventSink(
        os.environ.get("EVENT_DIR", "/var/log/hvab"),
        component="switch",
        pod=pod,
        domain=domain,
        run_id=os.environ.get("RUN_ID"),
    ) as sink:
        queues = SwitchQueueAccess(r, keys)
        switch = Switch(
            table=ForwardingTable(r, keys),
            queues=queues,
            sink=sink,
            egress_limit=int(os.environ.get("EGRESS_BYTES", "10485760")),
            log_malformed_prefix=os.environ.get("LOG_MALFORMED_PREFIX") == "1",
        )
        service = SwitchService(
            r,
            keys=keys,
            switch=switch,
            sink=sink,
            block_timeout=float(os.environ.get("BLOCK_TIMEOUT", "1")),
            sweep_interval=float(os.environ.get("SWEEP_INTERVAL", "1")),
            sweep_batch_per_port=int(os.environ.get("SWEEP_BATCH", "64")),
            hint_rate_per_port=float(os.environ.get("HINT_RATE_PER_PORT", "1000")),
        )
        service.run(lambda: stopping)


if __name__ == "__main__":
    main()
