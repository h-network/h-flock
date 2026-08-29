"""Delivery for port_type: openshell -- one-shot exec against a live sandbox.

Parallel to `deliver_tmux` in `.deliver`, but built around a fundamentally
different interaction model (see docs/LLD-port-openshell.md §2): OpenShell's
`ExecSandbox` spawns a fresh process and returns once it exits — there is no
"paste into an already-running pane" equivalent. So a `Message`/`Command`
delivery here means: invoke the target CLI non-interactively once, on the
long-lived sandbox that `StartAgent`/`StopAgent` (`flock.control`) already
created and will delete, and send its output back to the source via
`bus.doors.send` — the reply step tmux's own paste model never needs,
because a tmux pane has no return value to send anywhere.

This module is only ever imported lazily, through
`flock.port.registry`'s `(module_path, attr_name)` spec — never at the top
of `deliver.py` or `control/openers.py`, which stay cheap to import for
every tmux/api/control delivery (`flock.openshell` pulls in grpc/protobuf).
"""

from __future__ import annotations

from flock.bus import DeadLetter, EnvelopeError, parse, prefix
from flock.bus.doors import _emit_for_recipient, send
from flock.bus.envelope import parse_for_switch
from flock.openshell import OpenShellClient, OpenShellUnavailable, headless_command
from flock.openshell.naming import sandbox_name, workspace_name

from .deliver import drain_ingress
from .openers import add_ticket_opener


def _agent_cli(r, pod: str, tenant: str, agent: str) -> str:
    raw_cli = r.get(prefix(pod, tenant, agent=agent, resource="launch"))
    cli = raw_cli.decode() if isinstance(raw_cli, bytes) else raw_cli
    return cli or "claude"


def _exec_headless(client: OpenShellClient, sbx_name: str, cli: str, stdin_text: str):
    """Resolve the sandbox's current id and run one headless invocation.

    Always resumes (see docs/LLD-port-openshell.md §2a): confirmed safe for
    codex by direct testing against the live gateway — `resume --last` on a
    sandbox with no prior session silently starts a fresh one instead of
    erroring. Claude's equivalent (`-c`/`--continue` with nothing to
    continue) was not verified the same way — no credential was injected to
    test it, per this ticket's standing rule — so this is INFERRED correct
    for claude from documented CLI ergonomics, not observed. Confirm with a
    real credentialed run before trusting this claim.
    """
    ref = client.get_sandbox(sbx_name)
    command = headless_command(cli, resume=True)
    return client.exec_sandbox(ref.id, command, stdin=stdin_text.encode("utf-8"))


def _reply(r, pod: str, tenant: str, agent: str, destination: str, envelope: dict, result) -> None:
    text = result.stdout if result.exit_code == 0 else (result.stdout + result.stderr)
    if not text.strip():
        return
    send(
        r,
        pod=pod,
        tenant=tenant,
        source=agent,
        destination=destination,
        payload={"text": text},
        kind="Message",
        correlation_id=envelope.get("stream_id"),
        module="port",
    )


def _deliver_message(r, pod: str, tenant: str, agent: str, envelope: dict, client: OpenShellClient, sbx_name: str, cli: str) -> None:
    source = envelope.get("l2", {}).get("source", "unknown")
    payload = envelope.get("payload", {})
    text = payload.get("text", "") if isinstance(payload, dict) else str(payload)
    prompt = f"[message from {source}] {text}"

    result = _exec_headless(client, sbx_name, cli, prompt)
    _reply(r, pod, tenant, agent, source, envelope, result)


def _deliver_command(r, pod: str, tenant: str, agent: str, envelope: dict, client: OpenShellClient, sbx_name: str, cli: str) -> None:
    # No "[message from ...]" prefix -- same distinction tmux's Command
    # opener makes (docs/LLD-port-tmux.md §"Command — text to run, not text
    # to read"): the same one-shot exec, just unwrapped text.
    source = envelope.get("l2", {}).get("source", "unknown")
    payload = envelope.get("payload", {})
    text = payload.get("text", "") if isinstance(payload, dict) else str(payload)

    result = _exec_headless(client, sbx_name, cli, text)
    _reply(r, pod, tenant, agent, source, envelope, result)


def deliver_openshell(
    r,
    pod: str,
    tenant: str,
    agent: str,
    session_name: str | None = None,
    socket: str | None = None,
    timeout: int = 1,
    client: OpenShellClient | None = None,
    **kwargs,
) -> None:
    """`client` is accepted for tests: pass an `OpenShellClient` wrapping a
    fake `sandbox_client` (see `tests/test_openshell_client.py`'s
    `FakeSandboxClient`). The registry never passes it, so production
    delivery always builds a real one scoped to `pod:tenant`'s workspace.
    """
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

    cli = _agent_cli(r, pod, tenant, agent)
    sbx_name = sandbox_name(agent)
    owns_client = client is None
    client = client or OpenShellClient(workspace_name(pod, tenant))

    try:
        for raw, envelope in parsed_items:
            kind = envelope.get("kind")
            try:
                if kind == "Message":
                    _deliver_message(r, pod, tenant, agent, envelope, client, sbx_name, cli)
                elif kind == "Command":
                    _deliver_command(r, pod, tenant, agent, envelope, client, sbx_name, cli)
                elif kind == "AddTicket":
                    add_ticket_opener(
                        r=r, pod=pod, tenant=tenant, agent=agent, envelope=envelope,
                        session_name=session_name, socket=socket,
                    )
                elif kind == "Attachment":
                    # No dedicated file-write RPC confirmed in the OpenShell
                    # surface yet -- see docs/LLD-port-openshell.md §5.
                    raise DeadLetter("attachment delivery not yet implemented for port_type openshell")
                else:
                    raise DeadLetter(f"unknown kind: {kind}")
            except DeadLetter as exc:
                r.rpush(dead_key, raw)
                _emit_for_recipient("port", "dead_lettered", envelope, agent, str(exc))
                continue
            except OpenShellUnavailable as exc:
                r.rpush(dead_key, raw)
                _emit_for_recipient("port", "dead_lettered", envelope, agent, f"gateway_unavailable: {exc}")
                continue
            except Exception as exc:
                r.rpush(dead_key, raw)
                _emit_for_recipient("port", "dead_lettered", envelope, agent, f"opener failed: {exc}")
                continue
            _emit_for_recipient("port", "opened", envelope, agent)
    finally:
        if owns_client:
            client.close()
