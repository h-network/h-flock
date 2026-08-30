"""Ingress delivery for agents hosted in tmux windows."""

import os

from flock.bus import DeadLetter, EnvelopeError, parse, prefix
from flock.bus.doors import _emit_for_recipient
from flock.bus.envelope import parse_for_switch
from flock.port.deliver import drain_ingress
from flock.port.openers import add_ticket_opener

from .openers import attachment_opener, command_opener, messages_opener


def deliver_tmux(
    r,
    pod: str,
    tenant: str,
    agent: str,
    session_name: str | None = None,
    socket: str | None = None,
    timeout: int = 1,
    **kwargs,
) -> None:
    session_name = session_name or os.environ.get("TMUX_SESSION") or tenant
    socket = socket or os.environ.get("TMUX_SOCKET")
    ingress_key = prefix(pod, tenant, agent, "ingress")
    dead_key = prefix(pod, tenant, agent, "dead")

    raw_items = drain_ingress(r, ingress_key)
    if not raw_items:
        return

    parsed_items: list[tuple[str, dict]] = []
    for raw in raw_items:
        try:
            envelope = parse(raw)
        except EnvelopeError as exc:
            r.rpush(dead_key, raw)
            try:
                header = parse_for_switch(raw)
            except EnvelopeError:
                header = {}
            _emit_for_recipient("port", "dead_lettered", header, agent, str(exc))
            continue

        _emit_for_recipient("port", "received", envelope, agent)
        parsed_items.append((raw, envelope))

    if not parsed_items:
        return

    current_message_batch: list[tuple[str, dict]] = []

    def dead_letter(raw_item: str, envelope: dict, reason: str) -> None:
        r.rpush(dead_key, raw_item)
        _emit_for_recipient("port", "dead_lettered", envelope, agent, reason)

    def flush_messages() -> None:
        nonlocal current_message_batch
        if not current_message_batch:
            return
        batch = current_message_batch
        current_message_batch = []
        try:
            messages_opener(
                r=r,
                pod=pod,
                tenant=tenant,
                agent=agent,
                envelopes=[env for _, env in batch],
                session_name=session_name,
                socket=socket,
            )
        except DeadLetter as exc:
            for raw_item, envelope in batch:
                dead_letter(raw_item, envelope, str(exc))
            return
        except Exception as exc:
            for raw_item, envelope in batch:
                dead_letter(raw_item, envelope, f"opener failed: {exc}")
            return

        for _, envelope in batch:
            _emit_for_recipient("port", "opened", envelope, agent)

    for raw, envelope in parsed_items:
        kind = envelope.get("kind")
        if kind == "Message":
            current_message_batch.append((raw, envelope))
            continue

        flush_messages()
        if kind == "Command":
            opener = command_opener
            opener_kwargs = {"session_name": session_name, "socket": socket}
        elif kind == "AddTicket":
            opener = add_ticket_opener
            opener_kwargs = {}
        elif kind == "Attachment":
            opener = attachment_opener
            opener_kwargs = {"session_name": session_name, "socket": socket}
        else:
            dead_letter(raw, envelope, f"unknown kind: {kind}")
            continue

        try:
            opener(
                r=r,
                pod=pod,
                tenant=tenant,
                agent=agent,
                envelope=envelope,
                **opener_kwargs,
            )
        except DeadLetter as exc:
            dead_letter(raw, envelope, str(exc))
            continue
        except Exception as exc:
            dead_letter(raw, envelope, f"opener failed: {exc}")
            continue
        _emit_for_recipient("port", "opened", envelope, agent)

    flush_messages()
