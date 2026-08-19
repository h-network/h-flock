"""Administrative, idempotent phase-1 domain provisioning."""

import json
import os
from pathlib import Path
import time
import uuid

import redis

from .adapter import port_acl_rules
from .address import Address
from .errors import AddressInUse, PortNotDrained, PortStillAdmitting
from .events import EventSink
from .keys import Keys
from .redis_functions import load_functions
from .switch_service import _redis_url
from .table import Admission, ForwardingTable


def switch_acl_rules(keys: Keys) -> tuple[str, ...]:
    return (
        "reset",
        "on",
        "resetkeys",
        "resetchannels",
        "-@all",
        "+auth",
        "+ping",
        "+fcall",
        "+config|get",
        "+psubscribe",
        "+smembers",
        "+hget",
        "+hgetall",
        "+get",
        "+llen",
        "+lpop",
        "+decrby",
        "+set",
        "+rpush",
        "+incrby",
        f"~hvab:{keys.tag}:*",
        f"&{keys.hint_pattern}",
        "-eval",
        "-evalsha",
        "-function|load",
    )


def _password(item: dict) -> str:
    return Path(item["password_file"]).read_text().strip()


def _set_user(r, name: str, rules: tuple[str, ...], password: str) -> None:
    r.execute_command("ACL", "SETUSER", name, *rules, f">{password}")


def _checked_call(principal: str, function: str, call):
    try:
        return call()
    except redis.RedisError as exc:
        raise RuntimeError(
            f"ACL self-test failed for principal {principal!r}, "
            f"function {function!r}: {exc}"
        ) from exc


def _self_test_port(admin, client, keys: Keys, port: str, principal: str) -> None:
    """Exercise every station Function inside the port's real ACL pattern."""
    prefix = f"hvab:{keys.tag}:port:{port}:selftest:{uuid.uuid4().hex}"
    ingress = f"{prefix}:ingress"
    ingress_bytes = f"{prefix}:ingress-bytes"
    egress_bytes = f"{prefix}:egress-bytes"
    meta = f"{prefix}:meta"
    scratch = (ingress, ingress_bytes, egress_bytes, meta)
    generation = "selftest"
    try:
        admin.hset(meta, mapping={"state": "active", "generation": generation})
        _checked_call(
            principal,
            "hvab_admit",
            lambda: client.fcall(
                "hvab_admit",
                3,
                ingress,
                ingress_bytes,
                meta,
                b"selftest",
                port,
                generation,
                4096,
                keys.hint_channel(port),
            ),
        )
        admin.set(egress_bytes, 8)
        _checked_call(
            principal,
            "hvab_account_egress_pop",
            lambda: client.fcall("hvab_account_egress_pop", 1, egress_bytes, 8),
        )
        _checked_call(
            principal,
            "hvab_detach",
            lambda: client.fcall("hvab_detach", 1, meta, generation),
        )
    finally:
        admin.delete(*scratch)


def _self_test_switch(admin, client, keys: Keys, principal: str) -> None:
    """Exercise every switch Function inside the domain's real ACL pattern."""
    prefix = f"hvab:{keys.tag}:selftest:{uuid.uuid4().hex}"
    ingress = f"{prefix}:ingress"
    ingress_bytes = f"{prefix}:ingress-bytes"
    egress = f"{prefix}:egress"
    egress_bytes = f"{prefix}:egress-bytes"
    meta = f"{prefix}:meta"
    scratch = (ingress, ingress_bytes, egress, egress_bytes, meta)
    generation = "selftest"
    try:
        admin.rpush(ingress, b"selftest")
        admin.set(ingress_bytes, 8)
        _checked_call(
            principal,
            "hvab_pop_ingress",
            lambda: client.fcall("hvab_pop_ingress", 2, ingress, ingress_bytes),
        )
        admin.hset(meta, mapping={"state": "active", "generation": generation})
        _checked_call(
            principal,
            "hvab_enqueue_egress",
            lambda: client.fcall(
                "hvab_enqueue_egress",
                3,
                egress,
                egress_bytes,
                meta,
                b"selftest",
                generation,
                4096,
            ),
        )
    finally:
        admin.delete(*scratch)


def _principal_client(redis_url: str, username: str, password: str):
    return redis.Redis.from_url(redis_url, username=username, password=password)


def _ensure_binding(table: ForwardingTable, item: dict, sink: EventSink) -> None:
    address = Address.parse(item["address"], require_qualified=True)
    current = table.port_binding(item["port"])
    if current is not None:
        if current.address == address and current.generation == item["generation"]:
            return
    allowed = item.get("allowed_sources")
    admission = (
        Admission.any_source()
        if allowed is None
        else Admission.only(
            *(Address.parse(value, require_qualified=True) for value in allowed)
        )
    )
    if current is None:
        table.bind(address, item["port"], item["generation"], admission)
    else:
        try:
            depth = table.rebind(
                address, item["port"], item["generation"], admission
            )
        except (AddressInUse, PortNotDrained, PortStillAdmitting) as exc:
            sink.emit(
                "rebind_refused",
                port=item["port"],
                previous_address=str(current.address),
                new_address=str(address),
                condition=exc.code,
                observed_ingress_depth=getattr(exc, "depth", None),
                reason=str(exc),
            )
            raise
        sink.emit(
            "rebind_completed",
            port=item["port"],
            previous_address=str(current.address),
            new_address=str(address),
            observed_ingress_depth=depth,
        )


def main() -> None:
    config = json.loads(Path(os.environ["HVAB_PORTS_FILE"]).read_text())
    keys = Keys(config["pod"], config["domain"])
    redis_url = _redis_url()
    r = redis.Redis.from_url(redis_url)
    while True:
        try:
            r.ping()
            version = r.info("server")["redis_version"]
            break
        except (redis.ConnectionError, redis.TimeoutError):
            time.sleep(1)
    if version != "7.4.2":
        raise RuntimeError(f"deployment requires Redis 7.4.2, got {version}")
    load_functions(r)
    table = ForwardingTable(r, keys)
    with EventSink(
        os.environ.get("EVENT_DIR", "/var/log/hvab"),
        component="provision",
        pod=config["pod"],
        domain=config["domain"],
        run_id=os.environ.get("RUN_ID"),
    ) as sink:
        for item in config["ports"]:
            _ensure_binding(table, item, sink)
            password = _password(item)
            _set_user(
                r, item["user"], port_acl_rules(keys, item["port"]), password
            )
            client = _principal_client(redis_url, item["user"], password)
            try:
                _self_test_port(r, client, keys, item["port"], item["user"])
            finally:
                client.close()
        switch = config["switch"]
        password = _password(switch)
        _set_user(r, switch["user"], switch_acl_rules(keys), password)
        client = _principal_client(redis_url, switch["user"], password)
        try:
            _self_test_switch(r, client, keys, switch["user"])
        finally:
            client.close()


if __name__ == "__main__":
    main()
