"""Container entrypoint for one long-lived per-port delivery process."""

import importlib
import os
import signal

import redis

from .delivery import DeliveryService
from .events import EventSink
from .keys import Keys
from .queue import EgressReader
from .switch_service import _redis_url


def _handler():
    spec = os.environ.get("HVAB_HANDLER")
    if not spec:
        raise ValueError("HVAB_HANDLER is required for the delivery service")
    module_name, separator, attribute = spec.partition(":")
    if not separator:
        raise ValueError("HVAB_HANDLER must be 'module:function'")
    return os.environ["PACKET_TYPE"], getattr(importlib.import_module(module_name), attribute)


def main() -> None:
    pod = os.environ["POD"]
    domain = os.environ["DOMAIN"]
    port = os.environ["PORT"]
    packet_type, handler = _handler()
    handlers = {packet_type: handler}
    r = redis.Redis.from_url(_redis_url())
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with EventSink(
        os.environ.get("EVENT_DIR", "/var/log/hvab"),
        component="delivery",
        pod=pod,
        domain=domain,
        run_id=os.environ.get("RUN_ID"),
    ) as sink:
        service = DeliveryService(
            r,
            reader=EgressReader(r, Keys(pod, domain), port),
            sink=sink,
            target=os.environ["TARGET"],
            handlers=handlers,
            block_timeout=float(os.environ.get("BLOCK_TIMEOUT", "1")),
        )
        service.run(lambda: stopping)


if __name__ == "__main__":
    main()
