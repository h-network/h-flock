import base64
import os
from datetime import datetime, timezone

from flock.bus import DeadLetter, port_type, prefix
from flock.port.openers import (
    ATTACHMENT_MAX_BASE64_CHARS,
    ATTACHMENT_MAX_BYTES,
    BASE64_CHARS_REGEX,
    MIME_TYPE_REGEX,
)
from flock.tmux.ops import list_windows, submit_text

# The CLIs that write a session file the switch can tail. An agent running
# anything else — a bare shell — produces no activity, so a delivery to it can
# never be confirmed and must not be marked.
#
# ⚠ `agy` joined this set once `~/.gemini/antigravity-cli/history.jsonl` was
# confirmed live and wired into `ActivityTailer` (`watchdog/activity.py`'s
# `_agy_events`) — it records every submitted input, including a paste, so the
# same "input after the marker" aliveness check that verifies claude/codex now
# applies to agy too.
VERIFIABLE_CLIS = frozenset({"claude", "codex", "agy"})


def mark_delivery_pending(
    r,
    pod: str,
    tenant: str,
    agent: str,
    stream_id: str,
    correlation_id: str | None = None,
) -> None:
    """Record a pending delivery verification marker for a verifiable tmux CLI."""
    try:
        if not stream_id:
            return
        # ⚠ An allowlist, not "everything except agy". A marker is only useful
        # for a CLI whose activity we can tail, and anything else can never be
        # confirmed — so it would report unverified forever.
        #
        # Measured: a denylist marked bash windows too (an agent with no launch
        # key at all), and three of the first four unverified records in a live
        # run were those. A CLI we cannot tail must be skipped by default, not
        # by having been remembered.
        launch_key = prefix(pod, tenant, agent=agent, resource="launch")
        raw_cli = r.get(launch_key)
        cli = (raw_cli.decode() if isinstance(raw_cli, bytes) else str(raw_cli)) if raw_cli else ""
        if cli not in VERIFIABLE_CLIS:
            return

        verify_key = prefix(pod, tenant, agent=agent, resource="pending.verify")
        markers_key = prefix(pod, tenant, agent=agent, resource="delivery.markers")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        entry = {"stream_id": stream_id, "ts": ts}
        if correlation_id:
            entry["correlation_id"] = correlation_id
        r.xadd(
            verify_key,
            entry,
            maxlen=100,
            approximate=True,
        )
        # ⚠ 500 IS A SAFETY NET, NOT A POLICY, AND IT CAN LOSE ATTRIBUTION.
        # A marker trimmed here yields a usage record with no stream_id, which is
        # the degradation BUILD-82 §3 specifies — omit rather than guess — so the
        # loss is acceptable and bounded. It is NOT observable: a counter that
        # fired on every uncorrelated record was removed in review because 9 of
        # 27 uncorrelated in the live run were the normal case, and a signal
        # dominated by the normal case is the delivery_unverified defect again.
        # ⚠ Do not "fix" this with an XDEL on attribution. That was built once
        # and deleted the marker BEFORE the claim, turning a retryable XADD miss
        # into permanent loss and letting a duplicate delete a newer marker.
        r.xadd(
            markers_key,
            entry,
            maxlen=500,
            approximate=True,
        )
    except Exception:
        pass


def messages_opener(
    r,
    pod: str,
    tenant: str,
    agent: str,
    envelopes: list[dict],
    session_name: str,
    socket: str | None = None,
) -> None:
    if not envelopes:
        return

    windows = list_windows(session_name, socket=socket)
    if agent not in windows:
        raise DeadLetter("window_missing")

    blocks = []
    for envelope in envelopes:
        source = envelope.get("l2", {}).get("source", "unknown")
        payload = envelope.get("payload", {})
        text = payload.get("text", "") if isinstance(payload, dict) else str(payload)
        blocks.append(f"[message from {source}] {text}\n")
        try:
            pt = port_type(r, pod=pod, tenant=tenant, agent=source)
        except Exception:
            pt = None
        if pt == "api":
            blocks.append(f"[reply to {source}]\n")

    combined_msg = "".join(blocks)

    # ⚠ Mark BEFORE pasting. The CLI records its input the instant the text is
    # submitted, so a marker written afterwards can carry a later timestamp than
    # the very event meant to confirm it — a sub-second race the comparison then
    # loses. Measured: six deliveries all landed and five read unverified.
    #
    # Marking first costs nothing if the paste fails: the delivery genuinely did
    # not happen, and unverified is the right answer.
    for envelope in envelopes:
        stream_id = envelope.get("stream_id", "")
        corr_id = envelope.get("correlation_id")
        mark_delivery_pending(r, pod, tenant, agent, stream_id, correlation_id=corr_id)

    primary_stream_id = envelopes[0].get("stream_id", "")
    submit_text(session_name, agent, combined_msg, stream_id=primary_stream_id, socket=socket)


def message_opener(
    r,
    pod: str,
    tenant: str,
    agent: str,
    envelope: dict,
    session_name: str,
    socket: str | None = None,
) -> None:
    messages_opener(
        r=r,
        pod=pod,
        tenant=tenant,
        agent=agent,
        envelopes=[envelope],
        session_name=session_name,
        socket=socket,
    )


def command_opener(
    r,
    pod: str,
    tenant: str,
    agent: str,
    envelope: dict,
    session_name: str,
    socket: str | None = None,
) -> None:
    stream_id = envelope.get("stream_id", "")
    corr_id = envelope.get("correlation_id")
    source = envelope.get("l2", {}).get("source", "unknown")
    payload = envelope.get("payload", {})

    windows = list_windows(session_name, socket=socket)
    if agent not in windows:
        raise DeadLetter("window_missing")

    text = payload.get("text", "")
    formatted_msg = f"{text}\n"
    # ⚠ Mark BEFORE pasting. The CLI records its input the instant the text is
    # submitted, so a marker written afterwards can carry a later timestamp than
    # the very event meant to confirm it — a sub-second race the comparison then
    # loses. Measured: six deliveries all landed and five read unverified.
    #
    # Marking first costs nothing if the paste fails: the delivery genuinely did
    # not happen, and unverified is the right answer.
    mark_delivery_pending(r, pod, tenant, agent, stream_id, correlation_id=corr_id)
    submit_text(session_name, agent, formatted_msg, stream_id=stream_id, socket=socket)


def attachment_opener(
    r,
    pod: str,
    tenant: str,
    agent: str,
    envelope: dict,
    session_name: str,
    socket: str | None = None,
    workdir_root: str = "/workdir",
) -> None:
    if not isinstance(envelope, dict):
        raise DeadLetter("envelope must be a dict")

    stream_id = envelope.get("stream_id") or envelope.get("l2", {}).get("stream_id")
    if not stream_id or not isinstance(stream_id, str):
        raise DeadLetter("missing stream_id for attachment delivery")

    corr_id = envelope.get("correlation_id") or envelope.get("l2", {}).get("correlation_id")
    source = envelope.get("l2", {}).get("source", "unknown")

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

    # Validate filename: non-empty UTF-8 basename of at most 255 UTF-8 bytes.
    # May not be '.' or '..', contain '/', '\\', NUL, ASCII controls (< 32), or U+007F.
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

    # Validate mime_type: at most 255 ASCII bytes and matches ^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$
    try:
        mime_bytes = mime_type.encode("ascii")
    except UnicodeEncodeError as exc:
        raise DeadLetter(f"mime_type must be ASCII: {exc}") from exc
    if not (1 <= len(mime_bytes) <= 255):
        raise DeadLetter("mime_type length must be between 1 and 255 ASCII bytes")
    if not MIME_TYPE_REGEX.match(mime_type):
        raise DeadLetter(f"invalid mime_type format: {mime_type!r}")

    # Validate caption: at most 65,536 UTF-8 bytes
    if caption is not None:
        try:
            caption_bytes = caption.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise DeadLetter(f"caption utf-8 encoding error: {exc}") from exc
        if len(caption_bytes) > 65536:
            raise DeadLetter("caption exceeds 65536 UTF-8 bytes")

    # Validate content_base64:
    # RFC 4648 standard base64 with padding, decoded with strict alphabet validation.
    # URL-safe base64 and whitespace are rejected.
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

    # Check recipient tmux window exists
    windows = list_windows(session_name, socket=socket)
    if agent not in windows:
        raise DeadLetter("window_missing")

    # Create /workdir/<recipient>/attachments/<stream_id>/
    target_dir = os.path.join(workdir_root, agent, "attachments", stream_id)
    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception as exc:
        raise DeadLetter(f"failed to create attachment directory: {exc}") from exc

    final_path = os.path.join(target_dir, filename)
    temp_path = os.path.join(target_dir, f".tmp.{os.urandom(8).hex()}")

    try:
        with open(temp_path, "wb") as f:
            f.write(decoded_bytes)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, final_path)
    except Exception as exc:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise DeadLetter(f"attachment file write failed: {exc}") from exc

    # Deferred custody: write pending.verify / delivery.markers AFTER durable file write, BEFORE paste
    mark_delivery_pending(r, pod, tenant, agent, stream_id, correlation_id=corr_id)

    # Paste notice into window
    notice = f"[attachment from {source}] saved to {final_path} ({mime_type}, {len(decoded_bytes)} bytes)\n"
    if caption:
        notice += f"[attachment caption] {caption}\n"

    submit_text(session_name, agent, notice, stream_id=stream_id, socket=socket)
