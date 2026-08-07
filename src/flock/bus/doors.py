import json
from datetime import datetime, timezone
from typing import Callable, Any

from .envelope import build, parse, EnvelopeError
from .keys import prefix


def log_record(
    module: str,
    event: str,
    stream_id: str,
    correlation_id: str | None = None,
    producer: str | None = None,
    recipient: str | None = None,
    reason: str | None = None,
) -> None:
    rec: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "module": module,
        "event": event,
        "stream_id": stream_id,
    }
    if correlation_id:
        rec["correlation_id"] = correlation_id
    if producer:
        rec["producer"] = producer
    if recipient:
        rec["recipient"] = recipient
    if reason:
        rec["reason"] = reason
    print(json.dumps(rec), flush=True)


def send(
    r,
    *,
    pod: str,
    tenant: str,
    producer: str,
    recipient: str,
    payload: dict,
    kind: str = "Message",
    correlation_id: str | None = None,
) -> str:
    env = build(kind, producer, recipient, payload, correlation_id)
    egress_key = prefix(pod, tenant, agent=producer, resource="egress")
    raw = json.dumps(env)
    r.rpush(egress_key, raw)

    log_record(
        module="bus",
        event="sent",
        stream_id=env["stream_id"],
        correlation_id=env.get("correlation_id"),
        producer=producer,
        recipient=recipient,
    )
    return env["stream_id"]


def receive(
    r,
    *,
    pod: str,
    tenant: str,
    agent: str,
    openers: dict[str, Callable[[dict], None]],
    timeout: int = 5,
) -> None:
    ingress_key = prefix(pod, tenant, agent=agent, resource="ingress")
    res = r.blpop(ingress_key, timeout=timeout)
    if not res:
        return

    _, raw = res
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")

    try:
        env = parse(raw)
    except EnvelopeError as e:
        dead_key = prefix(pod, tenant, agent=agent, resource="dead")
        r.rpush(dead_key, raw)
        log_record(
            module="bus",
            event="dead_lettered",
            stream_id="unknown",
            recipient=agent,
            reason=str(e),
        )
        return

    stream_id = env.get("stream_id", "")
    corr_id = env.get("correlation_id")
    producer = env.get("producer")
    recipient = env.get("recipient")

    log_record(
        module="bus",
        event="received",
        stream_id=stream_id,
        correlation_id=corr_id,
        producer=producer,
        recipient=recipient,
    )

    kind = env.get("kind")
    if kind in openers:
        openers[kind](env)
    else:
        dead_key = prefix(pod, tenant, agent=agent, resource="dead")
        r.rpush(dead_key, raw)
        log_record(
            module="bus",
            event="dead_lettered",
            stream_id=stream_id,
            correlation_id=corr_id,
            producer=producer,
            recipient=recipient,
            reason="unknown_kind",
        )
