"""Delivery for port_type: openshell -- one-shot exec against a live sandbox.

Parallel to `deliver_tmux` in `flock.tmux.deliver`, but built around a fundamentally
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

import base64
import os

from flock.bus import DeadLetter, EnvelopeError, parse, prefix
from flock.bus.doors import _emit_for_recipient, send
from flock.bus.envelope import parse_for_switch
from flock.openshell import OpenShellClient, OpenShellUnavailable, headless_command
from flock.openshell.naming import sandbox_name, workspace_name

from .deliver import drain_ingress
from .openers import (
    ATTACHMENT_MAX_BASE64_CHARS,
    ATTACHMENT_MAX_BYTES,
    BASE64_CHARS_REGEX,
    MIME_TYPE_REGEX,
    add_ticket_opener,
)


def _agent_cli(r, pod: str, tenant: str, agent: str) -> str:
    raw_cli = r.get(prefix(pod, tenant, agent=agent, resource="launch"))
    cli = raw_cli.decode() if isinstance(raw_cli, bytes) else raw_cli
    return cli or "claude"


def _agent_profile(r, pod: str, tenant: str, agent: str) -> str | None:
    raw_profile = r.get(prefix(pod, tenant, agent=agent, resource="profile"))
    return raw_profile.decode() if isinstance(raw_profile, bytes) else raw_profile


# Real file paths a credentialed CLI reads from, confirmed directly against
# real credential files already present in this office's environment --
# their JSON *structure* was inspected (key names only, via a script that
# never printed a value), never their contents. See
# docs/openshell-credential-transfer-design.md §3b.
_CODEX_AUTH_PATH = "/sandbox/.codex/auth.json"
_AGY_AUTH_PATH = "/sandbox/.gemini/antigravity-cli/antigravity-oauth-token"
_CREDENTIAL_FILE_PATHS = {"codex": _CODEX_AUTH_PATH, "agy": _AGY_AUTH_PATH}
# Env var flock reads the whole credential file's content from, one profile
# at a time -- mirrors CLAUDE_OAUTH_TOKEN_<PROFILE>'s existing naming shape
# (flock.tmux.ops.window_env), just holding a full JSON blob instead of one
# bare token, since that's the real shape both files take.
_CREDENTIAL_ENV_VARS = {"codex": "CODEX_AUTH_JSON", "agy": "AGY_AUTH_JSON"}


def _profile_env_suffix(profile: str | None) -> str:
    return (profile or "default").upper().replace("-", "_")


def _write_credential_file(client: OpenShellClient, sandbox_id: str, path: str, content: bytes) -> None:
    dir_path = path.rsplit("/", 1)[0]
    b64_content = base64.b64encode(content).decode("ascii")
    script = 'mkdir -p "$1" && base64 -d > "$2"'
    result = client.exec_sandbox(
        sandbox_id, ["/bin/sh", "-c", script, "sh", dir_path, path], stdin=b64_content.encode("ascii")
    )
    if result.exit_code != 0:
        raise OpenShellUnavailable(f"failed to write credential file {path!r}: {result.stderr or result.stdout}")


def _wipe_credential_file(client: OpenShellClient, sandbox_id: str, path: str) -> None:
    """Best-effort: a failed wipe is not raised, matching
    `container/seed-home.sh`'s own `shred` (fallback `rm`) shape — a
    delivery that already succeeded or failed on its own terms should not
    also fail because cleanup couldn't run (e.g. the sandbox died mid-exec).
    Still attempted unconditionally, from a `finally`, precisely because it
    must run even when the actual delivery raised.
    """
    script = 'shred -u "$1" 2>/dev/null || rm -f "$1" 2>/dev/null || true'
    try:
        client.exec_sandbox(sandbox_id, ["/bin/sh", "-c", script, "sh", path])
    except OpenShellUnavailable:
        pass


def _exec_headless(
    client: OpenShellClient, sbx_name: str, cli: str, stdin_text: str, profile: str | None = None
):
    """Resolve the sandbox's current id and run one headless invocation.

    Always resumes (see docs/LLD-port-openshell.md §2a): confirmed safe for
    codex by direct testing against the live gateway — `resume --last` on a
    sandbox with no prior session silently starts a fresh one instead of
    erroring. Claude's equivalent (`-c`/`--continue` with nothing to
    continue) was not verified the same way — no credential was injected to
    test it, per this ticket's standing rule — so this is INFERRED correct
    for claude from documented CLI ergonomics, not observed. Confirm with a
    real credentialed run before trusting this claim.

    Credential shape is per-CLI (docs/openshell-credential-transfer-design.md):
    claude authenticates via `CLAUDE_CODE_OAUTH_TOKEN` passed only as this
    one `exec_sandbox` call's `env=` — proven for real against the live
    gateway, nothing ever written to disk. codex and agy are file-based
    (confirmed: no per-invocation env-var auth path exists for either), so
    for them the credential file is written immediately before this exec
    and wiped immediately after, in a `finally` — never persisted in
    `SandboxSpec.environment` at creation, never left behind if the exec
    itself fails.
    """
    ref = client.get_sandbox(sbx_name)
    command = headless_command(cli, resume=True)

    if cli == "claude":
        token = os.environ.get(f"CLAUDE_OAUTH_TOKEN_{_profile_env_suffix(profile)}")
        env = {"CLAUDE_CODE_OAUTH_TOKEN": token} if token else None
        return client.exec_sandbox(ref.id, command, stdin=stdin_text.encode("utf-8"), env=env)

    file_path = _CREDENTIAL_FILE_PATHS.get(cli)
    env_var_name = _CREDENTIAL_ENV_VARS.get(cli)
    if file_path is None or env_var_name is None:
        return client.exec_sandbox(ref.id, command, stdin=stdin_text.encode("utf-8"))

    credential_json = os.environ.get(f"{env_var_name}_{_profile_env_suffix(profile)}")
    if not credential_json:
        return client.exec_sandbox(ref.id, command, stdin=stdin_text.encode("utf-8"))

    _write_credential_file(client, ref.id, file_path, credential_json.encode("utf-8"))
    try:
        return client.exec_sandbox(ref.id, command, stdin=stdin_text.encode("utf-8"))
    finally:
        _wipe_credential_file(client, ref.id, file_path)


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


def _deliver_message(r, pod: str, tenant: str, agent: str, envelope: dict, client: OpenShellClient, sbx_name: str, cli: str, profile: str | None) -> None:
    source = envelope.get("l2", {}).get("source", "unknown")
    payload = envelope.get("payload", {})
    text = payload.get("text", "") if isinstance(payload, dict) else str(payload)
    prompt = f"[message from {source}] {text}"

    result = _exec_headless(client, sbx_name, cli, prompt, profile=profile)
    _reply(r, pod, tenant, agent, source, envelope, result)


def _deliver_command(r, pod: str, tenant: str, agent: str, envelope: dict, client: OpenShellClient, sbx_name: str, cli: str, profile: str | None) -> None:
    # No "[message from ...]" prefix -- same distinction tmux's Command
    # opener makes (docs/LLD-port-tmux.md §"Command — text to run, not text
    # to read"): the same one-shot exec, just unwrapped text.
    source = envelope.get("l2", {}).get("source", "unknown")
    payload = envelope.get("payload", {})
    text = payload.get("text", "") if isinstance(payload, dict) else str(payload)

    result = _exec_headless(client, sbx_name, cli, text, profile=profile)
    _reply(r, pod, tenant, agent, source, envelope, result)


def _write_attachment(
    client: OpenShellClient, sbx_name: str, stream_id: str, filename: str, decoded_bytes: bytes
) -> str:
    """Base64-decode-into-temp-file-then-atomic-mv via `exec_sandbox`.

    No dedicated file-write RPC is confirmed in the OpenShell surface (see
    docs/openshell-sdk-surface-inventory.md — `sandbox upload`/`download`
    use a real SSH session instead, which would need a new SSH-client
    dependency to reproduce; this reuses the already-proven `exec_sandbox`
    path with no new dependency, matching how tmux's own `attachment_opener`
    writes files with a plain `open()` — there just isn't a filesystem
    handle to open directly here).

    Base path is `/sandbox` — confirmed directly (`pwd`/`$HOME` inside a
    real sandbox), not `/workdir` (flock's own container convention,
    which does not exist inside an OpenShell sandbox at all: an earlier
    version of this used it and got a real `mkdir: /workdir: Permission
    denied`). No per-agent subdirectory either, unlike tmux's shared
    container — each sandbox already belongs to exactly one agent.

    `target_dir`/`temp_path`/`final_path` are passed as shell positional
    parameters (`$1`/`$2`/`$3`), not interpolated into the script text —
    `filename` is externally supplied (already validated by the caller,
    but this avoids depending on that validation alone for shell safety).
    """
    ref = client.get_sandbox(sbx_name)
    target_dir = f"/sandbox/attachments/{stream_id}"
    final_path = f"{target_dir}/{filename}"
    temp_path = f"{target_dir}/.tmp.{os.urandom(8).hex()}"
    b64_content = base64.b64encode(decoded_bytes).decode("ascii")
    script = 'mkdir -p "$1" && base64 -d > "$2" && mv -f "$2" "$3"'
    result = client.exec_sandbox(
        ref.id, ["/bin/sh", "-c", script, "sh", target_dir, temp_path, final_path],
        stdin=b64_content.encode("ascii"),
    )
    if result.exit_code != 0:
        raise DeadLetter(f"attachment write failed: {result.stderr or result.stdout}")
    return final_path


def _deliver_attachment(r, pod: str, tenant: str, agent: str, envelope: dict, client: OpenShellClient, sbx_name: str, cli: str, profile: str | None) -> None:
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise DeadLetter("attachment payload must be a dict")

    required_keys = {"filename", "mime_type", "content_base64"}
    allowed_keys = {"filename", "mime_type", "content_base64", "caption"}
    if not required_keys.issubset(payload.keys()):
        raise DeadLetter("missing required attachment payload fields")
    if not set(payload.keys()).issubset(allowed_keys):
        raise DeadLetter("unexpected attachment payload fields")

    filename = payload["filename"]
    mime_type = payload["mime_type"]
    content_base64 = payload["content_base64"]
    caption = payload.get("caption")

    if not isinstance(filename, str) or not isinstance(mime_type, str) or not isinstance(content_base64, str):
        raise DeadLetter("invalid attachment payload field types")
    if caption is not None and not isinstance(caption, str):
        raise DeadLetter("caption must be a string if present")

    # Same validation as flock.tmux.openers.attachment_opener --
    # filename: non-empty UTF-8 basename, at most 255 UTF-8 bytes, no path
    # separators/control chars/'.'/'..'.
    try:
        filename_bytes = filename.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise DeadLetter(f"filename utf-8 encoding error: {exc}") from exc
    if not (1 <= len(filename_bytes) <= 255):
        raise DeadLetter("filename length must be between 1 and 255 UTF-8 bytes")
    if filename in {".", ".."}:
        raise DeadLetter("filename cannot be '.' or '..'")
    if "/" in filename or "\\" in filename:
        raise DeadLetter("filename cannot contain path separators")
    if any(ord(c) < 32 or ord(c) == 127 for c in filename):
        raise DeadLetter("filename cannot contain ASCII control characters or DEL")

    try:
        mime_bytes = mime_type.encode("ascii")
    except UnicodeEncodeError as exc:
        raise DeadLetter(f"mime_type must be ASCII: {exc}") from exc
    if not (1 <= len(mime_bytes) <= 255):
        raise DeadLetter("mime_type length must be between 1 and 255 ASCII bytes")
    if not MIME_TYPE_REGEX.match(mime_type):
        raise DeadLetter(f"invalid mime_type format: {mime_type!r}")

    if caption is not None:
        try:
            caption_bytes = caption.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise DeadLetter(f"caption utf-8 encoding error: {exc}") from exc
        if len(caption_bytes) > 65536:
            raise DeadLetter("caption exceeds 65536 UTF-8 bytes")

    if len(content_base64) > ATTACHMENT_MAX_BASE64_CHARS:
        raise DeadLetter("content_base64 exceeds maximum allowed base64 length")
    if len(content_base64) % 4 != 0:
        raise DeadLetter("content_base64 length must be a multiple of 4")
    if not BASE64_CHARS_REGEX.match(content_base64):
        raise DeadLetter("content_base64 contains invalid characters or malformed padding")
    try:
        decoded_bytes = base64.b64decode(content_base64, validate=True)
    except Exception as exc:
        raise DeadLetter(f"content_base64 decode failed: {exc}") from exc
    if len(decoded_bytes) > ATTACHMENT_MAX_BYTES:
        raise DeadLetter(f"decoded attachment exceeds maximum size of {ATTACHMENT_MAX_BYTES} bytes")

    source = envelope.get("l2", {}).get("source", "unknown")
    stream_id = envelope.get("stream_id") or envelope.get("l2", {}).get("stream_id")
    if not stream_id or not isinstance(stream_id, str):
        raise DeadLetter("missing stream_id for attachment delivery")

    final_path = _write_attachment(client, sbx_name, stream_id, filename, decoded_bytes)

    notice = f"[attachment from {source}] saved to {final_path} ({mime_type}, {len(decoded_bytes)} bytes)"
    if caption:
        notice += f"\n[attachment caption] {caption}"

    result = _exec_headless(client, sbx_name, cli, notice, profile=profile)
    _reply(r, pod, tenant, agent, source, envelope, result)


def deliver_openshell(
    r,
    pod: str,
    tenant: str,
    agent: str,
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
    profile = _agent_profile(r, pod, tenant, agent)
    sbx_name = sandbox_name(agent)
    owns_client = client is None
    client = client or OpenShellClient(workspace_name(pod, tenant))

    try:
        for raw, envelope in parsed_items:
            kind = envelope.get("kind")
            try:
                if kind == "Message":
                    _deliver_message(r, pod, tenant, agent, envelope, client, sbx_name, cli, profile)
                elif kind == "Command":
                    _deliver_command(r, pod, tenant, agent, envelope, client, sbx_name, cli, profile)
                elif kind == "AddTicket":
                    add_ticket_opener(
                        r=r, pod=pod, tenant=tenant, agent=agent, envelope=envelope,
                    )
                elif kind == "Attachment":
                    _deliver_attachment(r, pod, tenant, agent, envelope, client, sbx_name, cli, profile)
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
