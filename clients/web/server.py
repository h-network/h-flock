#!/usr/bin/env python3
"""Serve the dependency-free office UI and proxy one h-flock tenant."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
from datetime import datetime
import os
import secrets
import signal
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit


HERE = Path(__file__).resolve().parent


def _parse_telegram_init_data(init_data: str) -> dict[str, str]:
    """Parse the query-string-shaped `initData` the Telegram Mini App SDK
    hands the page into a flat dict. Pure parsing — validates nothing."""
    return dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))


def verify_telegram_init_data(init_data: str, bot_token: str, *, max_age_s: int = 300) -> dict | None:
    """Validate `initData` per Telegram's own Mini App HMAC scheme — this is
    Telegram's signature, not ours, so it is implemented exactly as Telegram
    specifies rather than adapted: `secret_key = HMAC-SHA256("WebAppData",
    bot_token)`, then `HMAC-SHA256(secret_key, data_check_string)` over every
    field except `hash` itself, sorted `key=value` joined by `\\n`. Same
    HMAC-over-canonical-payload shape API.md's per-client `kid`/`sig`
    signatures already use — reused deliberately rather than inventing a
    second auth primitive.

    Returns the parsed field dict (with `user` decoded from its embedded
    JSON string) on success, `None` on any failure: bad signature, missing
    hash, unparseable input, or an `auth_date` outside `max_age_s`.
    ⚠ Telegram does not expire `initData` itself — a signature stays valid
    forever unless the caller checks `auth_date`, so a captured initData
    string would otherwise be a permanent login token. `max_age_s` (default
    300s) is that check; `abs()` also rejects a future-dated auth_date
    rather than only a stale one, which the interval check alone would miss.
    Never raises — every failure mode is a return of `None`.
    """
    if not init_data or not bot_token:
        return None
    try:
        fields = _parse_telegram_init_data(init_data)
        provided_hash = fields.pop("hash", None)
        if not provided_hash:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
        computed = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, provided_hash):
            return None
        auth_date = int(fields.get("auth_date", "0"))
        if auth_date <= 0 or abs(time.time() - auth_date) > max_age_s:
            return None
        if "user" in fields:
            fields["user"] = json.loads(fields["user"])
        return fields
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


# ⚠ An allowlist, not a denylist — exactly the `/api/...` paths
# mini-app.js's panels call (AgentsPanel, BoardsPanel, AlertsPanel), and
# nothing implied more broadly by "read-only". `/api/recordings`,
# `/api/audit` and `/conversation` are reads too, and none of them are on
# this list even though they were reachable before this was added — a
# review caught that the write/terminal boundary was reasoned carefully but
# GET was scoped only by what the current page happens to call, not by
# anything the server enforced. Recordings are byte-for-byte terminal
# capture, the audit log and conversation transcripts are full history —
# meaningfully more sensitive than the roster/alerts/board glance the Mini
# App actually shows, and an oversight relative to that framing, not a
# considered call. An allowlist rather than excluding those three by name
# also means a new api endpoint added later does not silently become
# reachable from a Mini App session just by existing.
_TELEGRAM_READ_ALLOWLIST_EXACT = {"/agents", "/board", "/alerts", "/alerts/stream"}


def _telegram_read_allowed(subpath: str) -> bool:
    """`subpath` is `self.path` with the leading `/api` and any query string
    removed. Allows `/agents/<name>` (bare presence) but not a deeper
    sub-resource like `/agents/<name>/activity`, `/agents/<name>/messages`
    or `/agents/<name>/board` — those are conversation- and activity-level
    detail, not the roster summary AgentsPanel reads.
    """
    path = subpath.split("?", 1)[0]
    if path in _TELEGRAM_READ_ALLOWLIST_EXACT:
        return True
    if path.startswith("/agents/"):
        rest = path[len("/agents/"):]
        return bool(rest) and "/" not in rest
    return False


def _load_config_file(config_path: str) -> dict[str, str | int | bool]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")
    content = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(content)
    elif path.suffix.lower() == ".toml":
        try:
            import tomllib
            return tomllib.loads(content)
        except ImportError:
            pass
    res = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";") or line.startswith("["):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            k = k.strip().replace("-", "_")
            v = v.strip().strip('"').strip("'")
            if v.lower() == "true":
                res[k] = True
            elif v.lower() == "false":
                res[k] = False
            elif v.isdigit():
                res[k] = int(v)
            else:
                res[k] = v
    return res


def _enforce_recordings_retention(rec_dir: Path, max_age_s: int = 7 * 86400, total_max_bytes: int = 100 * 1024 * 1024) -> None:
    if not rec_dir.exists():
        return
    now = time.time()
    files = []
    total_size = 0
    for p in rec_dir.glob("*.json"):
        try:
            stat = p.stat()
            mtime = stat.st_mtime
            if now - mtime > max_age_s:
                p.unlink(missing_ok=True)
            else:
                files.append((mtime, stat.st_size, p))
                total_size += stat.st_size
        except Exception:
            pass
    files.sort(key=lambda x: x[0])  # oldest first
    while total_size > total_max_bytes and files:
        mtime, size, p = files.pop(0)
        try:
            p.unlink(missing_ok=True)
            total_size -= size
        except Exception:
            pass


def _is_loopback(address: str) -> bool:
    addr = address.strip().lower()
    if addr in {"127.0.0.1", "localhost", "::1", "localhost.localdomain"}:
        return True
    if addr.startswith("127."):
        return True
    return False


def _read_socket_line(sock: socket.socket) -> str:
    buf = bytearray()
    while True:
        chunk = sock.recv(1)
        if not chunk:
            break
        buf.extend(chunk)
        if chunk == b"\n":
            break
    return buf.decode("latin1", errors="replace")


class OfficeHandler(SimpleHTTPRequestHandler):
    server_version = "h-flock-web/1"
    MAX_BODY_SIZE = 2 * 1024 * 1024  # 2MB cap to reject oversized POST payloads

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def setup(self) -> None:
        super().setup()
        try:
            self.request.settimeout(30.0)  # 30s timeout protects against slow-loris attacks
        except Exception:
            pass

    def _cookie_token(self) -> str | None:
        cookie_header = self.headers.get("Cookie", "")
        if not cookie_header:
            return None
        cookies = SimpleCookie()
        try:
            cookies.load(cookie_header)
        except Exception:
            return None
        session_cookie = cookies.get("hflock_session")
        return session_cookie.value if session_cookie and session_cookie.value else None

    def _session_is_telegram(self) -> bool:
        """True for a session that was authenticated via /api/telegram-auth
        rather than the operator secret — see verify_telegram_init_data.
        Read-only: _handle_telegram_auth is the only place that ever adds an
        entry, and only for a session it just created."""
        token = self._cookie_token()
        if not token:
            return False
        session_origin = getattr(self.server, "session_origin", {})
        return session_origin.get(token) == "telegram"

    def _is_authenticated(self) -> bool:
        secret = getattr(self.server, "secret", None)
        if not secret:
            return True
        token = self._cookie_token()
        if not token:
            return False
        lock = getattr(self.server, "sessions_lock", None)
        valid_sessions = getattr(self.server, "valid_sessions", {})
        if isinstance(valid_sessions, set):
            valid_sessions = {t: time.time() for t in valid_sessions}
            self.server.valid_sessions = valid_sessions

        session_ttl = getattr(self.server, "session_ttl", 86400)  # 24h lifetime
        now = time.time()
        session_origin = getattr(self.server, "session_origin", None)

        if lock is not None:
            with lock:
                # Expire old sessions
                expired = [t for t, created in valid_sessions.items() if now - created > session_ttl]
                for exp in expired:
                    del valid_sessions[exp]
                    if session_origin is not None:
                        session_origin.pop(exp, None)
                created = valid_sessions.get(token)
        else:
            expired = [t for t, created in valid_sessions.items() if now - created > session_ttl]
            for exp in expired:
                del valid_sessions[exp]
                if session_origin is not None:
                    session_origin.pop(exp, None)
            created = valid_sessions.get(token)

        if created is None:
            return False

        for valid_tok in list(valid_sessions.keys()):
            if hmac.compare_digest(token, valid_tok):
                return True
        return False

    def log_message(self, format: str, *args) -> None:
        log_fmt = getattr(self.server, "log_format", "text")
        if log_fmt == "json":
            status = args[0] if len(args) > 0 else ""
            record = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "client_ip": self.client_address[0],
                "method": self.command,
                "path": self.path,
                "status": status,
                "user_agent": self.headers.get("User-Agent", ""),
            }
            sys.stderr.write(json.dumps(record) + "\n")
            sys.stderr.flush()
        else:
            super().log_message(format, *args)

    def _get_session_id(self) -> str:
        token = self._cookie_token()
        return f"{token[:12]}..." if token else "unauthenticated"

    def _audit_log(self, event: str, details: dict, session_id: str | None = None) -> None:
        audit_file = getattr(self.server, "audit_log", None)
        if not audit_file:
            return
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            "session_id": session_id or self._get_session_id(),
            "client_ip": self.client_address[0],
            "user_agent": self.headers.get("User-Agent", ""),
            "details": details,
        }
        line = json.dumps(record) + "\n"
        max_bytes = getattr(self.server, "audit_max_bytes", 10 * 1024 * 1024)
        max_backups = getattr(self.server, "audit_max_backups", 5)

        def _do_write():
            path = Path(audit_file)
            path.parent.mkdir(parents=True, exist_ok=True)

            if path.exists() and path.stat().st_size >= max_bytes:
                for i in range(max_backups - 1, 0, -1):
                    s = Path(f"{audit_file}.{i}")
                    d = Path(f"{audit_file}.{i + 1}")
                    if s.exists():
                        s.rename(d)
                if path.exists():
                    path.rename(Path(f"{audit_file}.1"))

            with open(audit_file, "a", encoding="utf-8") as f:
                f.write(line)

        lock = getattr(self.server, "sessions_lock", None)
        try:
            if lock is not None:
                with lock:
                    _do_write()
            else:
                _do_write()
        except Exception as error:
            sys.stderr.write(f"CRITICAL: Audit log write failed for event '{event}': {error}\n")
            sys.stderr.flush()
            raise RuntimeError(f"audit log write failed: {error}") from error

    def _handle_post_recordings(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length > self.MAX_BODY_SIZE:
            self._json(413, {"detail": "payload too large"})
            return
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception as error:
            self._json(400, {"detail": f"invalid JSON payload: {error}"})
            return

        rec_dir = Path(getattr(self.server, "recordings_dir", HERE / "recordings"))
        rec_dir.mkdir(parents=True, exist_ok=True)

        max_recording_frames = getattr(self.server, "recording_max_frames", 5000)
        max_recording_bytes = getattr(self.server, "recording_max_bytes", 5 * 1024 * 1024)
        total_max_bytes = getattr(self.server, "recording_total_max_bytes", 100 * 1024 * 1024)
        max_age_s = getattr(self.server, "recording_max_age_s", 7 * 86400)

        _enforce_recordings_retention(rec_dir, max_age_s=max_age_s, total_max_bytes=total_max_bytes)

        if self.path.endswith("/frames"):
            # POST /api/recordings/<id>/frames
            parts = self.path.strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "api" and parts[1] == "recordings":
                rec_id = parts[2]
            else:
                self._json(400, {"detail": "invalid recording frames provider"})
                return
            safe_id = "".join(c for c in rec_id if c.isalnum() or c in ("-", "_"))
            rec_file = rec_dir / f"{safe_id}.json"
            if not rec_file.exists():
                self._json(404, {"detail": f"recording '{safe_id}' not found"})
                return

            try:
                rec_obj = json.loads(rec_file.read_text(encoding="utf-8"))
            except Exception:
                rec_obj = {"id": safe_id, "agent": "unknown", "frames": []}
            frames = rec_obj.get("frames", rec_obj.get("chunks", []))

            reason = None
            if rec_file.stat().st_size >= max_recording_bytes:
                reason = f"recording file size limit reached ({max_recording_bytes} bytes max)"
            elif len(frames) >= max_recording_frames:
                reason = f"recording frame count limit reached ({max_recording_frames} max)"

            if reason is not None:
                if not rec_obj.get("truncated"):
                    rec_obj["truncated"] = True
                    rec_obj["truncated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    rec_obj["truncate_reason"] = reason
                    rec_file.write_text(json.dumps(rec_obj, indent=2), encoding="utf-8")
                    self._audit_log("recording_truncated", {"id": safe_id, "reason": reason})
                self._json(413, {"detail": reason, "truncated": True})
                return

            frames.append(data)
            rec_obj["frames"] = frames
            rec_file.write_text(json.dumps(rec_obj, indent=2), encoding="utf-8")
            self._json(200, {"status": "appended", "frame_count": len(frames)})
            return

        # POST /api/recordings (create new recording)
        agent = data.get("agent", "unknown")
        raw_id = data.get("id") or data.get("session_id") or f"rec_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
        safe_id = "".join(c for c in str(raw_id) if c.isalnum() or c in ("-", "_"))
        iso_ts = data.get("created_at") or data.get("start_ts") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        rec_file = rec_dir / f"{safe_id}.json"
        rec_obj = {
            "id": safe_id,
            "session_id": safe_id,
            "agent": agent,
            "created_at": iso_ts,
            "start_ts": iso_ts,
            "frames": data.get("frames", data.get("chunks", [])),
        }
        rec_file.write_text(json.dumps(rec_obj, indent=2), encoding="utf-8")
        self._audit_log("recording_created", {
            "id": safe_id,
            "agent": agent,
        })
        self._json(201, {
            "id": safe_id,
            "session_id": safe_id,
            "agent": agent,
            "created_at": iso_ts,
        })

    def _handle_get_recordings(self) -> None:
        rec_dir = Path(getattr(self.server, "recordings_dir", HERE / "recordings"))
        if not rec_dir.exists():
            rec_dir.mkdir(parents=True, exist_ok=True)

        if self.path in {"/api/recordings", "/api/recordings/"}:
            recordings_list = []
            for path in rec_dir.glob("*.json"):
                try:
                    meta = json.loads(path.read_text(encoding="utf-8"))
                    frames = meta.get("frames", meta.get("chunks", []))
                    rec_id = meta.get("id", meta.get("session_id", path.stem))
                    recordings_list.append({
                        "id": rec_id,
                        "session_id": rec_id,
                        "agent": meta.get("agent", "unknown"),
                        "created_at": meta.get("created_at", meta.get("start_ts", "")),
                        "frame_count": len(frames),
                        "size_bytes": path.stat().st_size,
                    })
                except Exception:
                    pass
            recordings_list.sort(key=lambda r: r.get("created_at", ""), reverse=True)
            self._json(200, recordings_list)
        else:
            session_id = self.path.removeprefix("/api/recordings/").strip("/")
            safe_session_id = "".join(c for c in session_id if c.isalnum() or c in ("-", "_"))
            rec_file = rec_dir / f"{safe_session_id}.json"
            if not rec_file.exists():
                self._json(404, {"detail": f"recording '{safe_session_id}' not found"})
                return
            content = rec_file.read_text(encoding="utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

    def _handle_get_conversation(self) -> None:
        parts = self.path.split("?")[0].strip("/").split("/")
        agent_name = parts[2] if len(parts) >= 4 else "architect"
        client_name = getattr(self.server, "client_name", "web")

        outbound = []
        audit_file = getattr(self.server, "audit_log", None)
        if audit_file and Path(audit_file).exists():
            try:
                for line in Path(audit_file).read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    if rec.get("event") == "operator_action":
                        det = rec.get("details", {})
                        path = det.get("path", "")
                        if f"/agents/{agent_name}" in path or det.get("agent") == agent_name:
                            payload = det.get("payload", {})
                            text = payload.get("text") or (payload.get("payload", {}).get("text") if isinstance(payload.get("payload"), dict) else "")
                            if text:
                                outbound.append({
                                    "ts": rec.get("timestamp", ""),
                                    "kind": "Message",
                                    "source": client_name,
                                    "destination": agent_name,
                                    "direction": "outbound",
                                    "payload": {"text": text},
                                })
            except Exception:
                pass

        inbound = []
        if getattr(self.server, "demo_mode", False):
            inbound = [
                {
                    "ts": "2026-08-10T02:35:00Z",
                    "kind": "Message",
                    "source": agent_name,
                    "destination": client_name,
                    "direction": "inbound",
                    "payload": {"text": f"Build complete and verified for {agent_name}."},
                },
            ]
            outbound.append({
                "ts": "2026-08-10T02:30:00Z",
                "kind": "Message",
                "source": client_name,
                "destination": agent_name,
                "direction": "outbound",
                "payload": {"text": f"Can you check the build status for {agent_name}?"},
            })
        else:
            token = getattr(self.server, "api_token", "")
            headers = {"Authorization": f"Bearer {token}"} if token else {}

            # Replies delivered to client's mailbox (/agents/{client_name}/messages) filtered source == agent_name
            try:
                req = urllib.request.Request(
                    f"{self.server.api_base}/agents/{client_name}/messages",
                    headers=headers,
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode())
                        for msg in data.get("messages", []):
                            if msg.get("l2", {}).get("source") == agent_name:
                                msg["direction"] = "inbound"
                                msg["source"] = msg["l2"]["source"]
                                msg["destination"] = msg["l2"].get("destination", client_name)
                                inbound.append(msg)
            except Exception:
                pass

        combined = []
        seen = set()
        for msg in (outbound + inbound):
            text = msg.get("payload", {}).get("text") if isinstance(msg.get("payload"), dict) else str(msg.get("payload"))
            source = msg.get("l2", {}).get("source", msg.get("source"))
            key = f"{msg.get('ts')}:{source}:{text}"
            if key not in seen:
                seen.add(key)
                combined.append(msg)

        # ⚠ Do not sort these as strings. The audit record is second-granular
        # ("...:49Z") and a mailbox entry carries milliseconds ("...:49.123Z"),
        # and lexicographically "Z" sorts after ".", so every prompt landed AFTER
        # its own reply — a conversation with the answer above the question.
        # Parse to a real instant, and break a genuine tie with outbound first.
        def _instant(value: str) -> float:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                return 0.0

        combined.sort(key=lambda m: (_instant(m.get("ts", "")), 0 if m.get("direction") == "outbound" else 1))

        for idx, m in enumerate(combined):
            m["cursor"] = f"conv-{idx}"

        qs = urllib.parse.parse_qs(urlsplit(self.path).query)
        after_cursor = qs.get("after", [""])[0]
        if after_cursor:
            filtered = []
            found = False
            for m in combined:
                if found:
                    filtered.append(m)
                elif m["cursor"] == after_cursor:
                    found = True
            combined = filtered

        self._json(200, {"agent": agent_name, "messages": combined})

    def _handle_get_audit(self) -> None:
        audit_file = getattr(self.server, "audit_log", None)
        qs = urllib.parse.parse_qs(urlsplit(self.path).query)
        limit = min(500, max(1, int(qs.get("limit", ["50"])[0])))
        offset = max(0, int(qs.get("offset", ["0"])[0]))
        event_filter = qs.get("event", [""])[0]
        session_filter = qs.get("session_id", [""])[0]
        ip_filter = qs.get("client_ip", [""])[0]
        agent_filter = qs.get("agent", [""])[0]
        search_query = qs.get("q", [""])[0].lower()

        records = []
        if audit_file and Path(audit_file).exists():
            audit_path = Path(audit_file)
            files = [audit_path]
            for i in range(1, 10):
                b = Path(f"{audit_file}.{i}")
                if b.exists():
                    files.append(b)
            for f in files:
                try:
                    lines = f.read_text(encoding="utf-8").strip().splitlines()
                    for line in lines:
                        if not line.strip():
                            continue
                        rec = json.loads(line)
                        if event_filter and rec.get("event") != event_filter:
                            continue
                        if session_filter and session_filter not in rec.get("session_id", ""):
                            continue
                        if ip_filter and rec.get("client_ip") != ip_filter:
                            continue
                        if agent_filter:
                            det = rec.get("details", {})
                            det_agent = det.get("agent") or det.get("target") or (det.get("payload", {}) if isinstance(det.get("payload"), dict) else {}).get("agent", "")
                            if agent_filter not in str(det_agent):
                                continue
                        if search_query:
                            line_lower = line.lower()
                            if search_query not in line_lower:
                                continue
                        records.append(rec)
                except Exception:
                    pass

        records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        total = len(records)
        paged = records[offset : offset + limit]
        self._json(200, {
            "total": total,
            "limit": limit,
            "offset": offset,
            "records": paged,
        })

    def _handle_readyz(self) -> None:
        if getattr(self.server, "demo_mode", False):
            self._json(200, {"status": "ready", "mode": "demo"})
            return
        try:
            target = f"{self.server.api_base}/agents"
            req = urllib.request.Request(target, headers={"Authorization": f"Bearer {self.server.api_token}"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    self._json(200, {"status": "ready"})
                    return
        except Exception as error:
            self._json(503, {"status": "not_ready", "detail": f"upstream API unreachable: {error}"})

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
        elif self.path == "/readyz":
            self._handle_readyz()
        elif self.path == "/client-config":
            self._json(200, {
                "client": self.server.client_name,
                "demo": self.server.demo_mode,
                "auth_required": bool(getattr(self.server, "secret", None)),
                "authenticated": self._is_authenticated(),
                "read_only": self._session_is_telegram(),
            })
        elif getattr(self.server, "secret", None) and not self._is_authenticated():
            if self.path == "/login.html" or self.path == "/style.css":
                super().do_GET()
            elif self.path.startswith("/api/") or self.path.startswith("/session") or self.headers.get("Upgrade", "").lower() == "websocket":
                self._json(401, {"detail": "authentication required"})
            else:
                self._serve_login_page()
        elif (self.path.startswith("/session") or self.headers.get("Upgrade", "").lower() == "websocket") and self._session_is_telegram():
            # ⚠ No terminal for a Mini App session, full stop — not "read-only
            # terminal", refused outright. Enforcing read-only *within* the
            # session-door protocol means parsing and rewriting the proxied
            # WebSocket frames server-side; skipped for v1 in favour of a
            # boundary simple enough to be obviously correct. See the PR note.
            self._json(403, {"detail": "terminal access is not available from a Telegram Mini App session"})
        elif self.path.startswith("/api/") and self._session_is_telegram() and not _telegram_read_allowed(self.path.removeprefix("/api")):
            # See _telegram_read_allowed — recordings, the audit log and
            # conversation transcripts are all reachable through this same
            # generic prefix and are not on the allowlist.
            self._json(403, {"detail": "this session cannot read that resource"})
        elif self.path == "/" or self.path.startswith("/?"):
            self.path = "/index.html"
            super().do_GET()
        elif self.path == "/api/recordings" or self.path.startswith("/api/recordings/"):
            self._handle_get_recordings()
        elif self.path == "/api/audit" or self.path.startswith("/api/audit?") or self.path.startswith("/api/audit/"):
            self._handle_get_audit()
        elif "/conversation" in self.path:
            self._handle_get_conversation()
        elif self.server.demo_mode and self.path.startswith("/api/"):
            self._demo_api()
        elif self.path.startswith("/api/"):
            self._proxy()
        elif self.path.startswith("/session") or self.headers.get("Upgrade", "").lower() == "websocket":
            if self.server.demo_mode:
                self._demo_websocket()
            else:
                self._proxy_websocket()
        else:
            super().do_GET()

    def do_POST(self) -> None:
        if self.path == "/login":
            self._handle_login()
        elif self.path == "/api/telegram-auth":
            self._handle_telegram_auth()
        elif self.path == "/logout":
            self._handle_logout()
        elif getattr(self.server, "secret", None) and not self._is_authenticated():
            self._json(401, {"detail": "authentication required"})
        elif self.path.startswith("/api/") and self._session_is_telegram():
            # Every POST /api/* is a write (envelopes, lifecycle, recordings)
            # — a Telegram Mini App session is read-only in v1, full stop.
            self._json(403, {"detail": "this session is read-only"})
        elif self.path == "/api/recordings" or self.path.startswith("/api/recordings/"):
            self._handle_post_recordings()
        elif self.path.startswith("/api/"):
            length = int(self.headers.get("Content-Length", "0"))
            if length > self.MAX_BODY_SIZE:
                self._json(413, {"detail": "request body too large (max 2MB)"})
                return
            body = self.rfile.read(length) if length else None
            if body:
                try:
                    payload_data = json.loads(body.decode("utf-8"))
                    kind = payload_data.get("kind") or "Message"
                    self._audit_log("operator_action", {
                        "kind": kind,
                        "path": self.path,
                        "payload": payload_data.get("payload", payload_data)
                    })
                except Exception:
                    self._audit_log("operator_action", {
                        "kind": "Message",
                        "path": self.path,
                        "raw_bytes": len(body)
                    })
            if self.server.demo_mode:
                self._demo_api()
            else:
                self._proxy(body=body)
        else:
            self.send_error(404)

    def _handle_login(self) -> None:
        client_ip = self.client_address[0]
        now = time.time()
        lock = getattr(self.server, "sessions_lock", None)
        login_attempts = getattr(self.server, "login_attempts", {})
        rate_limit_window = getattr(self.server, "rate_limit_window", 60)  # 60 seconds
        max_attempts = getattr(self.server, "max_login_attempts", 5)  # max 5 failed attempts per min

        if lock is not None:
            with lock:
                attempts = [t for t in login_attempts.get(client_ip, []) if now - t < rate_limit_window]
                login_attempts[client_ip] = attempts
                if len(attempts) >= max_attempts:
                    self.send_response(429)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Retry-After", str(int(rate_limit_window)))
                    self.end_headers()
                    self.wfile.write(json.dumps({"detail": "too many login attempts, please try again later"}).encode("utf-8"))
                    return

        length = int(self.headers.get("Content-Length", "0"))
        if length > self.MAX_BODY_SIZE:
            self._json(413, {"detail": "payload too large"})
            return
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception:
            data = {}
        provided_secret = data.get("secret", "")
        secret = getattr(self.server, "secret", None)
        if secret and hmac.compare_digest(provided_secret, secret):
            token = secrets.token_hex(32)
            valid_sessions = getattr(self.server, "valid_sessions", None)
            if valid_sessions is not None:
                if isinstance(valid_sessions, set):
                    valid_sessions = {t: now for t in valid_sessions}
                    self.server.valid_sessions = valid_sessions
                if lock is not None:
                    with lock:
                        valid_sessions[token] = now
                        login_attempts.pop(client_ip, None)
                else:
                    valid_sessions[token] = now
                    login_attempts.pop(client_ip, None)
            cookie_header = f"hflock_session={token}; Path=/; HttpOnly; SameSite=Strict"
            if getattr(self.server, "api_base", "").startswith("https://"):
                cookie_header += "; Secure"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", cookie_header)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps({"authenticated": True}).encode("utf-8"))
            session_id_str = token[:12] + "..."
            self._audit_log("login_success", {}, session_id=session_id_str)
        else:
            if lock is not None:
                with lock:
                    attempts = login_attempts.get(client_ip, [])
                    attempts.append(now)
                    login_attempts[client_ip] = attempts
            else:
                attempts = login_attempts.get(client_ip, [])
                attempts.append(now)
                login_attempts[client_ip] = attempts
            self._audit_log("login_failure", {"reason": "invalid operator secret"})
            self._json(401, {"detail": "invalid operator secret"})

    def _handle_telegram_auth(self) -> None:
        """POST /api/telegram-auth — the Mini App's login, alongside /login's
        operator-secret one. A session created here is functionally identical
        to a normal one (same cookie, same valid_sessions entry, same
        session_ttl) except it is additionally recorded in session_origin as
        "telegram", which do_GET/do_POST use to refuse every write and the
        terminal socket for it — see _session_is_telegram. This is a second
        way to *reach* an existing session, not a second authorization model.
        """
        client_ip = self.client_address[0]
        now = time.time()
        lock = getattr(self.server, "sessions_lock", None)
        login_attempts = getattr(self.server, "login_attempts", {})
        rate_limit_window = getattr(self.server, "rate_limit_window", 60)
        max_attempts = getattr(self.server, "max_login_attempts", 5)

        if lock is not None:
            with lock:
                attempts = [t for t in login_attempts.get(client_ip, []) if now - t < rate_limit_window]
                login_attempts[client_ip] = attempts
                if len(attempts) >= max_attempts:
                    self.send_response(429)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Retry-After", str(int(rate_limit_window)))
                    self.end_headers()
                    self.wfile.write(json.dumps({"detail": "too many login attempts, please try again later"}).encode("utf-8"))
                    return

        bot_token = getattr(self.server, "telegram_bot_token", None)
        allowed_user_id = getattr(self.server, "telegram_allowed_user_id", None)
        if not bot_token or not allowed_user_id:
            self._json(404, {"detail": "Telegram Mini App login is not configured for this console"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        if length > self.MAX_BODY_SIZE:
            self._json(413, {"detail": "payload too large"})
            return
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception:
            data = {}

        fields = verify_telegram_init_data(data.get("initData", ""), bot_token)
        user_id = str(fields.get("user", {}).get("id", "")) if fields else ""
        # ⚠ Cryptographic validity alone is not authorization. `fields` being
        # non-None proves this really came from Telegram for THIS bot; it
        # says nothing about WHO — anyone who opens the bot gets valid,
        # correctly-signed initData for themselves. The chat_id allowlist
        # check is what refuses everyone but the configured operator, same
        # "no config means refuse everyone" rule bot.py's _chat_allowed uses.
        if not fields or not hmac.compare_digest(user_id, str(allowed_user_id)):
            if lock is not None:
                with lock:
                    attempts = login_attempts.get(client_ip, [])
                    attempts.append(now)
                    login_attempts[client_ip] = attempts
            else:
                attempts = login_attempts.get(client_ip, [])
                attempts.append(now)
                login_attempts[client_ip] = attempts
            self._audit_log("telegram_auth_failure", {"user_id": user_id or "unknown"})
            self._json(401, {"detail": "not authorized for this console"})
            return

        token = secrets.token_hex(32)
        valid_sessions = getattr(self.server, "valid_sessions", None)
        session_origin = getattr(self.server, "session_origin", None)
        if valid_sessions is not None:
            if lock is not None:
                with lock:
                    valid_sessions[token] = now
                    if session_origin is not None:
                        session_origin[token] = "telegram"
                    login_attempts.pop(client_ip, None)
            else:
                valid_sessions[token] = now
                if session_origin is not None:
                    session_origin[token] = "telegram"
                login_attempts.pop(client_ip, None)
        cookie_header = f"hflock_session={token}; Path=/; HttpOnly; SameSite=Strict"
        if getattr(self.server, "api_base", "").startswith("https://"):
            cookie_header += "; Secure"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", cookie_header)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps({"authenticated": True, "read_only": True}).encode("utf-8"))
        self._audit_log("telegram_auth_success", {"user_id": user_id}, session_id=f"{token[:12]}...")

    def _handle_logout(self) -> None:
        self._audit_log("logout", {})
        tok = self._cookie_token()
        if tok:
            lock = getattr(self.server, "sessions_lock", None)
            valid_sessions = getattr(self.server, "valid_sessions", None)
            session_origin = getattr(self.server, "session_origin", None)

            def _forget():
                if valid_sessions is not None:
                    valid_sessions.pop(tok, None)
                if session_origin is not None:
                    session_origin.pop(tok, None)

            if lock is not None:
                with lock:
                    _forget()
            else:
                _forget()
        clear_cookie = "hflock_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", clear_cookie)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps({"authenticated": False}).encode("utf-8"))

    def _serve_login_page(self) -> None:
        html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>h-flock Operator Login</title>
  <link rel="stylesheet" href="/style.css">
  <!-- Telegram's own official Mini App SDK -- same telegram.org domain
       clients/telegram/bot.py already talks to (api.telegram.org). Loaded
       from Telegram directly rather than vendored: it defines window.Telegram
       harmlessly (initData just empty) in any normal browser, so this script
       tag is inert outside an actual Telegram WebView. -->
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    body { display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; background: #0f172a; color: #f8fafc; font-family: system-ui, sans-serif; }
    .card { background: #1e293b; padding: 2rem; border-radius: 0.5rem; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.5); width: 100%; max-width: 400px; border: 1px solid #334155; }
    h2 { margin-top: 0; font-size: 1.25rem; }
    input[type="password"] { width: 100%; padding: 0.75rem; margin: 1rem 0; border: 1px solid #475569; border-radius: 0.25rem; background: #0f172a; color: #fff; box-sizing: border-box; }
    button { width: 100%; padding: 0.75rem; background: #2563eb; color: #fff; border: none; border-radius: 0.25rem; font-weight: 600; cursor: pointer; }
    button:hover { background: #1d4ed8; }
    .error { color: #f87171; font-size: 0.875rem; display: none; margin-top: 0.5rem; }
    .hint { color: #94a3b8; font-size: 0.8rem; margin-top: 0.75rem; }
  </style>
</head>
<body>
  <div class="card" id="card">
    <h2 id="card-title">h-flock Operator Login</h2>
    <p id="telegram-status" class="hint" style="display:none;">Signing in via Telegram…</p>
    <form id="login-form">
      <label for="secret">Operator Secret</label>
      <input type="password" id="secret" name="secret" required autofocus placeholder="Enter shared secret">
      <button type="submit">Sign In</button>
      <div id="error" class="error">Invalid operator secret</div>
    </form>
  </div>
  <script>
    // Mini App auto-login: if this page is running inside Telegram's WebView
    // (real initData present, not just the SDK script having loaded), skip
    // the manual secret form entirely and authenticate via initData instead
    // -- see server.py's _handle_telegram_auth for what's actually checked.
    // A read-only mini-app session lands on /mini.html, never / (the
    // full write-capable console), matching the deliberately smaller v1
    // surface this session gets.
    (function () {
      const tg = window.Telegram && window.Telegram.WebApp;
      if (!tg || !tg.initData) return;
      document.getElementById("login-form").style.display = "none";
      document.getElementById("telegram-status").style.display = "block";
      try { tg.ready(); tg.expand(); } catch (e) {}
      fetch("/api/telegram-auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: tg.initData })
      }).then((res) => {
        if (res.ok) { window.location.href = "/mini.html"; return; }
        document.getElementById("telegram-status").textContent = "Telegram sign-in failed. This chat isn't authorized for this console.";
      }).catch(() => {
        document.getElementById("telegram-status").textContent = "Connection error contacting the console.";
      });
    })();

    document.getElementById("login-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const secret = document.getElementById("secret").value;
      const err = document.getElementById("error");
      err.style.display = "none";
      try {
        const res = await fetch("/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ secret })
        });
        if (res.ok) {
          window.location.href = "/";
        } else {
          err.textContent = res.status === 429 ? "Too many failed attempts. Try again in 60s." : "Invalid operator secret";
          err.style.display = "block";
        }
      } catch (ex) {
        err.textContent = "Connection error";
        err.style.display = "block";
      }
    });
  </script>
</body>
</html>"""
        body = html.encode("utf-8")
        # The login document is the successful representation of this public
        # route. Protected API and socket requests still return 401; returning
        # 401 for the HTML itself makes browsers report a failed page resource.
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self, body: bytes | None = None) -> None:
        target = self.server.api_base + self.path.removeprefix("/api")
        if body is None and self.command in {"POST", "PUT", "PATCH"}:
            length = int(self.headers.get("Content-Length", "0"))
            if length > self.MAX_BODY_SIZE:
                self._json(413, {"detail": "request body too large (max 2MB)"})
                return
            body = self.rfile.read(length) if length else None

        headers = {"Authorization": f"Bearer {self.server.api_token}"}
        if body is not None:
            headers["Content-Type"] = self.headers.get("Content-Type", "application/json")
        if last_id := self.headers.get("Last-Event-ID"):
            headers["Last-Event-ID"] = last_id
        request = urllib.request.Request(target, data=body, headers=headers, method=self.command)
        try:
            response = urllib.request.urlopen(request)
        except urllib.error.HTTPError as error:
            response = error
        except urllib.error.URLError as error:
            self._json(502, {"detail": f"tenant unavailable: {error.reason}"})
            return

        self.send_response(response.status)
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        if content_type.startswith("text/event-stream"):
            self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            while chunk := response.read(8192):
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            response.close()

    def _proxy_websocket(self) -> None:
        self.close_connection = True
        if getattr(self.server, "secret", None) and not self._is_authenticated():
            self._json(401, {"detail": "authentication required"})
            return

        lock = getattr(self.server, "sessions_lock", None)
        max_sessions = getattr(self.server, "max_sessions", 16)

        if lock is not None:
            with lock:
                active = getattr(self.server, "active_sessions", 0)
                if active >= max_sessions:
                    self._json(503, {"detail": f"maximum active terminal sessions ({max_sessions}) reached"})
                    return
                self.server.active_sessions = active + 1

        try:
            self._do_proxy_websocket()
        finally:
            if lock is not None:
                with lock:
                    self.server.active_sessions = max(0, getattr(self.server, "active_sessions", 1) - 1)

    def _do_proxy_websocket(self) -> None:
        session_host = self.server.session_host
        session_port = self.server.session_port

        try:
            upstream_sock = socket.create_connection((session_host, session_port), timeout=10)
        except OSError as error:
            self._json(502, {"detail": f"session service unavailable: {error}"})
            return

        req_lines = [f"{self.command} {self.path} HTTP/1.1"]
        req_lines.append(f"Host: {session_host}:{session_port}")
        req_lines.append(f"Authorization: Bearer {self.server.api_token}")

        for key, value in self.headers.items():
            key_lower = key.lower()
            if key_lower not in {"host", "authorization"}:
                req_lines.append(f"{key}: {value}")

        req_bytes = ("\r\n".join(req_lines) + "\r\n\r\n").encode("utf-8")

        try:
            upstream_sock.sendall(req_bytes)
        except OSError:
            upstream_sock.close()
            self._json(502, {"detail": "failed to write to session service"})
            return

        status_line = _read_socket_line(upstream_sock)
        if not status_line:
            upstream_sock.close()
            self._json(502, {"detail": "empty response from session service"})
            return

        response_headers = [status_line]
        while True:
            line = _read_socket_line(upstream_sock)
            if not line or line in ("\r\n", "\n"):
                response_headers.append("\r\n")
                break
            response_headers.append(line)

        client_sock = self.request
        try:
            client_sock.sendall("".join(response_headers).encode("latin1"))
        except OSError:
            upstream_sock.close()
            return

        if not (status_line.startswith("HTTP/1.1 101") or status_line.startswith("HTTP/1.0 101")):
            upstream_sock.close()
            return

        buf = getattr(self.rfile, "_buffer", b"")
        if buf:
            try:
                upstream_sock.sendall(bytes(buf))
            except Exception:
                pass

        def forward(src, dst):
            try:
                while True:
                    data = src.recv(8192)
                    if not data:
                        break
                    dst.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except Exception:
                    pass

        lock = getattr(self.server, "sessions_lock", None)
        active_sockets = getattr(self.server, "active_sockets_set", None)
        if lock and active_sockets is not None:
            with lock:
                active_sockets.add(client_sock)

        try:
            t1 = threading.Thread(target=forward, args=(client_sock, upstream_sock), daemon=True)
            t2 = threading.Thread(target=forward, args=(upstream_sock, client_sock), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        finally:
            if lock and active_sockets is not None:
                with lock:
                    active_sockets.discard(client_sock)

    def _demo_api(self) -> None:
        subpath = self.path.removeprefix("/api")
        clean_subpath = subpath.split("?")[0]
        if clean_subpath == "/agents":
            self._json(200, {"agents": ["architect", "sme-2", "sme-3", "lab"]})
        elif clean_subpath == "/agents/architect":
            self._json(200, {
                "agent": "architect", "port_type": "tmux",
                "depths": {"ingress": 0, "egress": 0, "dead": 0},
                "presence": {"state": "working", "since": "2026-08-10T02:00:00Z", "last_activity": "2026-08-10T02:45:00Z"},
            })
        elif clean_subpath == "/agents/sme-2":
            self._json(200, {
                "agent": "sme-2", "port_type": "tmux",
                "depths": {"ingress": 1, "egress": 0, "dead": 0},
                "presence": {"state": "idle", "since": "2026-08-10T02:10:00Z", "last_activity": "2026-08-10T02:30:00Z"},
            })
        elif clean_subpath == "/agents/sme-3":
            self._json(200, {
                "agent": "sme-3", "port_type": "tmux",
                "depths": {"ingress": 2, "egress": 0, "dead": 0},
                "presence": {"state": "blocked", "since": "2026-08-10T02:15:00Z", "last_activity": "2026-08-10T02:20:00Z"},
            })
        elif clean_subpath == "/agents/lab":
            self._json(200, {
                "agent": "lab", "port_type": "tmux",
                "depths": {"ingress": 0, "egress": 0, "dead": 0},
                "presence": {"state": "unknown", "since": "", "last_activity": ""},
            })
        elif clean_subpath == "/board":
            self._json(200, {
                "agents": [
                    {
                        "agent": "architect",
                        "todo": [
                            {"id": "t-1", "title": "Build 33 UI console review"},
                            "Legacy bare ticket string in todo queue",
                        ],
                        "doing": [{"id": "t-2", "title": "Integrate same-origin WebSocket proxy"}],
                        "hold": [],
                        "done": [
                            {"id": "t-0", "title": "Setup repository structure"},
                            "Raw unformatted ticket string #42",
                        ],
                    },
                    {
                        "agent": "sme-2",
                        "todo": [{"id": "t-3", "title": "Audit documentation mentions"}],
                        "doing": [],
                        "hold": [],
                        "done": ["Bare string completed task"],
                    },
                    {
                        "agent": "sme-3",
                        "todo": [],
                        "doing": [{"id": "t-4", "title": "Investigate wedged CLI"}],
                        "hold": [],
                        "done": [],
                    },
                    {
                        "agent": "lab",
                        "todo": [],
                        "doing": [],
                        "hold": [],
                        "done": [],
                    },
                ]
            })
        elif clean_subpath == "/alerts":
            demo_alerts = [
                {
                    "cursor": f"{1000 + i}-0",
                    "ts": f"2026-08-10T02:{i % 60:02d}:00Z",
                    "kind": "stalled" if i % 2 == 0 else "credential",
                    "agent": f"sme-{(i % 3) + 1}",
                    "doing_age_s": (i + 1) * 30,
                    "account": "claude" if i % 2 != 0 else None,
                }
                for i in range(300)
            ]
            self._json(200, {
                "alerts": demo_alerts,
                "next_cursor": demo_alerts[-1]["cursor"],
            })
        elif clean_subpath == "/alerts/stream" or clean_subpath.startswith("/alerts/stream"):
            self._demo_sse([
                ("100-0", "alert", {"cursor": "100-0", "ts": "2026-08-10T02:20:00Z", "kind": "stalled", "agent": "sme-3", "doing_age_s": 900}),
                ("101-0", "alert", {"cursor": "101-0", "ts": "2026-08-10T02:25:00Z", "kind": "credential", "account": "claude", "detail": "expired"}),
            ])
        elif clean_subpath.endswith("/activity/stream"):
            self._demo_sse([
                ("act-1", "activity", {"cursor": "act-1", "ts": "2026-08-10T02:30:00Z", "kind": "tool", "tool": "pytest", "agent": "architect"}),
            ])
        elif clean_subpath.endswith("/activity"):
            agent_name = clean_subpath.split("/")[2] if len(clean_subpath.split("/")) > 2 else "architect"
            self._json(200, {
                "activity": [
                    {
                        "cursor": "act-0",
                        "ts": "2026-08-10T02:32:00Z",
                        "kind": "tool",
                        "tool": "pytest",
                        "agent": agent_name,
                    },
                    {
                        "cursor": "act-1",
                        "ts": "2026-08-10T02:34:00Z",
                        "kind": "tool",
                        "tool": "git",
                        "agent": agent_name,
                    }
                ]
            })
        elif clean_subpath.endswith("/messages/stream"):
            self._demo_sse([
                ("msg-1", "message", {"cursor": "msg-1", "ts": "2026-08-10T02:35:00Z", "kind": "Message", "source": "architect", "destination": "web", "payload": {"text": "Please review Build 33 console UI."}}),
            ])
        elif clean_subpath.endswith("/messages"):
            agent_name = clean_subpath.split("/")[2] if len(clean_subpath.split("/")) > 2 else "architect"
            self._json(200, {
                "messages": [
                    {
                        "cursor": "msg-0",
                        "ts": "2026-08-10T02:30:00Z",
                        "kind": "Message",
                        "source": "operator",
                        "destination": agent_name,
                        "payload": {"text": f"Can you check the latest build changes for {agent_name}?"}
                    },
                    {
                        "cursor": "msg-1",
                        "ts": "2026-08-10T02:35:00Z",
                        "kind": "Message",
                        "source": agent_name,
                        "destination": "operator",
                        "payload": {"text": f"Review complete. All 260 unit tests pass and presence is verified."}
                    }
                ]
            })
        elif clean_subpath.endswith("/envelopes") and self.command == "POST":
            self._json(202, {"stream_id": "demo-stream-1", "correlation_id": "demo-corr-1"})
        else:
            self._json(200, {"status": "ok"})

    def _demo_sse(self, events: list[tuple[str, str, dict]]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for event_id, event_type, data in events:
                payload = f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(data)}\n\n"
                self.wfile.write(payload.encode("utf-8"))
                self.wfile.flush()
            while True:
                time.sleep(2)
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _demo_websocket(self) -> None:
        self.close_connection = True
        client_sock = self.request
        ws_key = self.headers.get("Sec-WebSocket-Key", "")
        if ws_key:
            accept_src = ws_key.encode("utf-8") + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
            accept_key = base64.b64encode(hashlib.sha1(accept_src).digest()).decode("utf-8")
        else:
            accept_key = "demo-accept"

        resp = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key}\r\n\r\n"
        )
        try:
            client_sock.sendall(resp.encode())

            def encode_unmasked_frame(opcode: int, payload: bytes) -> bytes:
                b1 = 0x80 | (opcode & 0x0F)
                length = len(payload)
                if length < 126:
                    header = bytes([b1, length])
                elif length <= 65535:
                    header = bytes([b1, 126]) + length.to_bytes(2, "big")
                else:
                    header = bytes([b1, 127]) + length.to_bytes(8, "big")
                return header + payload

            welcome_msg = b"\x1b[32m[demo terminal connected]\x1b[0m\r\n$ "
            client_sock.sendall(encode_unmasked_frame(0x1, welcome_msg))

            buffer = bytearray()
            while True:
                data = client_sock.recv(4096)
                if not data:
                    break
                buffer.extend(data)
                while len(buffer) >= 2:
                    fin_opcode = buffer[0]
                    opcode = fin_opcode & 0x0F
                    has_mask = bool(buffer[1] & 0x80)
                    length = buffer[1] & 0x7F
                    idx = 2
                    if length == 126:
                        if len(buffer) < 4:
                            break
                        length = int.from_bytes(buffer[2:4], "big")
                        idx = 4
                    elif length == 127:
                        if len(buffer) < 10:
                            break
                        length = int.from_bytes(buffer[2:10], "big")
                        idx = 10

                    mask_key = b""
                    if has_mask:
                        if len(buffer) < idx + 4:
                            break
                        mask_key = buffer[idx : idx + 4]
                        idx += 4

                    if len(buffer) < idx + length:
                        break

                    raw_payload = buffer[idx : idx + length]
                    buffer = buffer[idx + length :]

                    if has_mask:
                        unmasked_payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(raw_payload))
                    else:
                        unmasked_payload = bytes(raw_payload)

                    if opcode == 0x8:  # Close frame
                        client_sock.sendall(encode_unmasked_frame(0x8, b""))
                        return
                    elif opcode == 0x9:  # Ping frame
                        client_sock.sendall(encode_unmasked_frame(0xA, unmasked_payload))
                    elif opcode in (0x1, 0x2):  # Text or Binary frame
                        client_sock.sendall(encode_unmasked_frame(opcode, unmasked_payload))
        except Exception:
            pass

    def _json(self, status: int, value: object) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def enrol(api_base: str, token: str, client: str) -> None:
    body = json.dumps(
        {"kind": "StartAgent", "payload": {"agent": client, "port_type": "api"}}
    ).encode()
    request = urllib.request.Request(
        f"{api_base}/agents/host/envelopes",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        if response.status != 202:
            raise RuntimeError(f"enrolment returned HTTP {response.status}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the h-flock browser client")
    parser.add_argument("--config", help="Path to config file (.toml, .json, key-value)")
    parser.add_argument("--listen", default=os.environ.get("WEB_LISTEN"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("WEB_PORT", "0")) if os.environ.get("WEB_PORT") else None)
    parser.add_argument("--api", default=os.environ.get("HFLOCK_API"))
    parser.add_argument("--session", default=os.environ.get("HFLOCK_SESSION"))
    parser.add_argument("--token", default=os.environ.get("API_TOKEN"))
    parser.add_argument("--client", default=os.environ.get("HFLOCK_CLIENT"))
    parser.add_argument("--secret", default=os.environ.get("HFLOCK_SECRET"))
    parser.add_argument("--tls-cert", default=os.environ.get("HFLOCK_TLS_CERT"))
    parser.add_argument("--tls-key", default=os.environ.get("HFLOCK_TLS_KEY"))
    parser.add_argument("--log-format", choices=["text", "json"], default=os.environ.get("HFLOCK_LOG_FORMAT", "text"))
    parser.add_argument("--audit-log", default=os.environ.get("HFLOCK_AUDIT_LOG"))
    parser.add_argument("--demo", action="store_true", default=None)
    # Same variable names clients/telegram/bot.py already uses for the same
    # bot and the same single operator — a Mini App login is "prove you're
    # the same person the bot already only talks to", not a second identity
    # to configure. Both required together; either absent disables the
    # feature and /api/telegram-auth answers 404 (§ _handle_telegram_auth).
    parser.add_argument("--telegram-bot-token", default=os.environ.get("TELEGRAM_BOT_TOKEN"))
    parser.add_argument("--telegram-chat-id", default=os.environ.get("TELEGRAM_CHAT_ID"))
    args = parser.parse_args()

    cfg: dict[str, str | int | bool] = {}
    if args.config:
        try:
            cfg = _load_config_file(args.config)
        except Exception as error:
            parser.error(f"failed to load config file: {error}")

    listen = args.listen or str(cfg.get("listen", "127.0.0.1"))
    port = args.port or int(cfg.get("port", 8090))
    api_url = args.api or str(cfg.get("api", "http://127.0.0.1:8080"))
    session_url = args.session or str(cfg.get("session", "http://127.0.0.1:8081"))
    token = args.token or (str(cfg.get("token")) if cfg.get("token") else None)
    client = args.client or str(cfg.get("client", "web"))
    secret = args.secret or (str(cfg.get("secret")) if cfg.get("secret") else None)
    tls_cert = args.tls_cert or (str(cfg.get("tls_cert")) if cfg.get("tls_cert") else None)
    tls_key = args.tls_key or (str(cfg.get("tls_key")) if cfg.get("tls_key") else None)
    log_format = args.log_format if args.log_format != "text" else str(cfg.get("log_format", "text"))
    audit_log = args.audit_log or (str(cfg.get("audit_log")) if cfg.get("audit_log") else None)
    if not audit_log:
        # ⚠ Default it on. The audit log is not only an audit log — it is the
        # ONLY record of what the operator sent, and the conversation view
        # replays it to rebuild their side after a reload. Left off, the console
        # silently loses every message you typed the moment you refresh, and it
        # looks exactly like data loss rather than an unset flag. Reported by an
        # operator who lost a conversation that way. Pass --audit-log to move it.
        audit_log = str(Path(__file__).resolve().parent / "console-audit.jsonl")

    demo_mode = args.demo if args.demo is not None else bool(cfg.get("demo", bool(os.environ.get("HFLOCK_DEMO"))))
    token = token or ("demo-secret" if demo_mode else None)

    if audit_log:
        try:
            p = Path(audit_log)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                pass
        except Exception as error:
            print(
                f"ERROR: Cannot write to audit log path '{audit_log}': {error}\n"
                f"Refusing to start console without a verified writable audit log path.",
                file=sys.stderr,
            )
            raise SystemExit(1)

    if not _is_loopback(listen) and not secret:
        print(
            f"ERROR: Refusing to bind non-loopback interface '{listen}' without operator secret authentication.\n"
            f"Provide --secret or set HFLOCK_SECRET or secret in config to enable access control before exposing the console over the network.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not token and not demo_mode:
        parser.error("provide --token, API_TOKEN, or token in --config")

    api_base = api_url.rstrip("/")
    session_host = "127.0.0.1"
    session_port = 8081

    if not demo_mode:
        parsed = urlsplit(api_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            parser.error("--api must be an absolute http(s) URL")

        parsed_session = urlsplit(session_url)
        if parsed_session.scheme not in {"http", "https", "ws", "wss"} or not parsed_session.netloc:
            parser.error("--session must be an absolute http(s) or ws(s) URL")
        session_host = parsed_session.hostname or "127.0.0.1"
        session_port = parsed_session.port or 8081

        try:
            enrol(api_base, token, client)
        except (urllib.error.URLError, RuntimeError) as error:
            print(f"could not enrol {client}: {error}", file=sys.stderr)
            raise SystemExit(1) from error

    server = ThreadingHTTPServer((listen, port), OfficeHandler)
    server.api_base = api_base
    server.session_host = session_host
    server.session_port = session_port
    server.api_token = token
    server.client_name = client
    server.demo_mode = demo_mode
    server.secret = secret
    server.log_format = log_format
    server.audit_log = audit_log
    server.valid_sessions = {}  # token -> created_timestamp
    server.session_origin = {}  # token -> "telegram", for sessions from _handle_telegram_auth only
    server.telegram_bot_token = args.telegram_bot_token or (str(cfg.get("telegram_bot_token")) if cfg.get("telegram_bot_token") else None)
    server.telegram_allowed_user_id = args.telegram_chat_id or (str(cfg.get("telegram_chat_id")) if cfg.get("telegram_chat_id") else None)
    server.session_ttl = int(os.environ.get("HFLOCK_SESSION_TTL", "86400"))  # 24 hours
    server.login_attempts = {}  # ip -> list of timestamp attempts
    server.max_login_attempts = int(os.environ.get("HFLOCK_MAX_LOGIN_ATTEMPTS", "5"))
    server.rate_limit_window = int(os.environ.get("HFLOCK_RATE_LIMIT_WINDOW", "60"))
    server.max_sessions = int(os.environ.get("HFLOCK_MAX_SESSIONS", "16"))
    server.active_sessions = 0
    server.active_sockets_set = set()
    server.sessions_lock = threading.Lock()

    scheme = "http"
    if tls_cert and tls_key:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=tls_cert, keyfile=tls_key)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        scheme = "https"

    def _shutdown_handler(signum, frame):
        print(f"\nReceived signal {signum}, initiating graceful shutdown...", file=sys.stderr)
        with server.sessions_lock:
            for s in list(server.active_sockets_set):
                try:
                    s.sendall(b"\x88\x00")
                    s.shutdown(socket.SHUT_RDWR)
                    s.close()
                except Exception:
                    pass
            server.active_sockets_set.clear()
        threading.Thread(target=server.shutdown, daemon=True).start()

    try:
        signal.signal(signal.SIGTERM, _shutdown_handler)
        signal.signal(signal.SIGINT, _shutdown_handler)
    except Exception:
        pass

    mode_str = " (DEMO MODE)" if demo_mode else ""
    auth_str = " [AUTH REQUIRED]" if secret else ""
    tls_str = " [TLS ENABLED]" if tls_cert else ""
    print(f"office UI: {scheme}://{listen}:{port} (client {client}){mode_str}{auth_str}{tls_str}")
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
