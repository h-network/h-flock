#!/usr/bin/env python3
"""Serve the dependency-free office UI and proxy one h-flock tenant."""

from __future__ import annotations

import argparse
import hmac
import json
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
from urllib.parse import urlsplit


HERE = Path(__file__).resolve().parent


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

    def _is_authenticated(self) -> bool:
        secret = getattr(self.server, "secret", None)
        if not secret:
            return True
        cookie_header = self.headers.get("Cookie", "")
        if not cookie_header:
            return False
        cookies = SimpleCookie()
        try:
            cookies.load(cookie_header)
        except Exception:
            return False
        session_cookie = cookies.get("hflock_session")
        if not session_cookie or not session_cookie.value:
            return False
        token = session_cookie.value
        lock = getattr(self.server, "sessions_lock", None)
        valid_sessions = getattr(self.server, "valid_sessions", {})
        if isinstance(valid_sessions, set):
            valid_sessions = {t: time.time() for t in valid_sessions}
            self.server.valid_sessions = valid_sessions

        session_ttl = getattr(self.server, "session_ttl", 86400)  # 24h lifetime
        now = time.time()

        if lock is not None:
            with lock:
                # Expire old sessions
                expired = [t for t, created in valid_sessions.items() if now - created > session_ttl]
                for exp in expired:
                    del valid_sessions[exp]
                created = valid_sessions.get(token)
        else:
            expired = [t for t, created in valid_sessions.items() if now - created > session_ttl]
            for exp in expired:
                del valid_sessions[exp]
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
        cookie_header = self.headers.get("Cookie", "")
        if cookie_header:
            cookies = SimpleCookie()
            try:
                cookies.load(cookie_header)
                if "hflock_session" in cookies:
                    return cookies["hflock_session"].value[:12] + "..."
            except Exception:
                pass
        return "unauthenticated"

    def _audit_log(self, event: str, details: dict) -> None:
        audit_file = getattr(self.server, "audit_log", None)
        if not audit_file:
            return
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            "session_id": self._get_session_id(),
            "client_ip": self.client_address[0],
            "user_agent": self.headers.get("User-Agent", ""),
            "details": details,
        }
        line = json.dumps(record) + "\n"
        lock = getattr(self.server, "sessions_lock", None)
        if lock is not None:
            with lock:
                with open(audit_file, "a", encoding="utf-8") as f:
                    f.write(line)
        else:
            with open(audit_file, "a", encoding="utf-8") as f:
                f.write(line)

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
            })
        elif getattr(self.server, "secret", None) and not self._is_authenticated():
            if self.path == "/login.html" or self.path == "/style.css":
                super().do_GET()
            elif self.path.startswith("/api/") or self.path.startswith("/session") or self.headers.get("Upgrade", "").lower() == "websocket":
                self._json(401, {"detail": "authentication required"})
            else:
                self._serve_login_page()
        elif self.path == "/" or self.path.startswith("/?"):
            self.path = "/index.html"
            super().do_GET()
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
        elif self.path == "/logout":
            self._handle_logout()
        elif getattr(self.server, "secret", None) and not self._is_authenticated():
            self._json(401, {"detail": "authentication required"})
        elif self.path.startswith("/api/"):
            length = int(self.headers.get("Content-Length", "0"))
            if length > self.MAX_BODY_SIZE:
                self._json(413, {"detail": "request body too large (max 2MB)"})
                return
            body = self.rfile.read(length) if length else None
            if body:
                try:
                    payload_data = json.loads(body.decode("utf-8"))
                    kind = payload_data.get("kind", "")
                    if kind:
                        self._audit_log("operator_action", {"kind": kind, "path": self.path, "payload": payload_data.get("payload", {})})
                except Exception:
                    pass
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
            self._audit_log("login_success", {})
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

    def _handle_logout(self) -> None:
        self._audit_log("logout", {})
        cookie_header = self.headers.get("Cookie", "")
        if cookie_header:
            cookies = SimpleCookie()
            try:
                cookies.load(cookie_header)
                if "hflock_session" in cookies:
                    tok = cookies["hflock_session"].value
                    lock = getattr(self.server, "sessions_lock", None)
                    valid_sessions = getattr(self.server, "valid_sessions", None)
                    if valid_sessions is not None:
                        if lock is not None:
                            with lock:
                                valid_sessions.pop(tok, None)
                        else:
                            valid_sessions.pop(tok, None)
            except Exception:
                pass
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
  <title>h-flock Console — Authentication Required</title>
  <style>
    body { display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #0d1117; color: #c9d1d9; font-family: monospace, system-ui; }
    .login-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 2rem; width: 360px; box-shadow: 0 8px 24px rgba(0,0,0,0.5); }
    .login-card h2 { margin-top: 0; color: #58a6ff; font-size: 1.25rem; }
    .login-card label { display: block; margin-bottom: 0.5rem; font-size: 0.875rem; color: #8b949e; }
    .login-card input[type="password"] { width: 100%; padding: 0.5rem; border: 1px solid #30363d; border-radius: 4px; background: #0d1117; color: #c9d1d9; font-size: 1rem; box-sizing: border-box; margin-bottom: 1rem; }
    .login-card button { width: 100%; padding: 0.6rem; border: none; border-radius: 4px; background: #238636; color: white; font-weight: bold; cursor: pointer; }
    .login-card button:hover { background: #2ea043; }
    .error-msg { color: #f85149; font-size: 0.85rem; margin-top: 0.75rem; display: none; }
  </style>
</head>
<body>
  <div class="login-card">
    <h2>h-flock Console</h2>
    <p style="font-size: 0.85rem; color: #8b949e; margin-bottom: 1.25rem;">Operator secret required to access console & terminal.</p>
    <form id="login-form">
      <label for="secret-input">Operator Secret</label>
      <input type="password" id="secret-input" autocomplete="current-password" required placeholder="Enter HFLOCK_SECRET">
      <button type="submit">Unlock Console</button>
      <div id="error-msg" class="error-msg">Invalid operator secret</div>
    </form>
  </div>
  <script>
    document.getElementById("login-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const secret = document.getElementById("secret-input").value;
      const err = document.getElementById("error-msg");
      err.style.display = "none";
      try {
        const resp = await fetch("/login", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({secret})
        });
        if (resp.ok) {
          window.location.reload();
        } else {
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
        self.send_response(401)
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

        if self.command == "POST" and body:
            try:
                payload_data = json.loads(body.decode("utf-8"))
                kind = payload_data.get("kind", "")
                if kind:
                    self._audit_log("operator_action", {"kind": kind, "path": self.path, "payload": payload_data.get("payload", {})})
            except Exception:
                pass

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
                "agent": "architect", "vab": "tmux",
                "depths": {"ingress": 0, "egress": 0, "dead": 0},
                "presence": {"state": "working", "since": "2026-08-10T02:00:00Z", "last_activity": "2026-08-10T02:45:00Z"},
            })
        elif clean_subpath == "/agents/sme-2":
            self._json(200, {
                "agent": "sme-2", "vab": "tmux",
                "depths": {"ingress": 1, "egress": 0, "dead": 0},
                "presence": {"state": "idle", "since": "2026-08-10T02:10:00Z", "last_activity": "2026-08-10T02:30:00Z"},
            })
        elif clean_subpath == "/agents/sme-3":
            self._json(200, {
                "agent": "sme-3", "vab": "tmux",
                "depths": {"ingress": 2, "egress": 0, "dead": 0},
                "presence": {"state": "blocked", "since": "2026-08-10T02:15:00Z", "last_activity": "2026-08-10T02:20:00Z"},
            })
        elif clean_subpath == "/agents/lab":
            self._json(200, {
                "agent": "lab", "vab": "tmux",
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
        elif clean_subpath.endswith("/messages/stream"):
            self._demo_sse([
                ("msg-1", "message", {"cursor": "msg-1", "ts": "2026-08-10T02:35:00Z", "kind": "Message", "producer": "architect", "recipient": "web", "payload": {"text": "Please review Build 33 console UI."}}),
            ])
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
        resp = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: demo-accept\r\n\r\n"
        )
        try:
            client_sock.sendall(resp.encode())
            while True:
                data = client_sock.recv(8192)
                if not data:
                    break
                client_sock.sendall(data)
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
        {"kind": "StartAgent", "payload": {"agent": client, "vab": "api"}}
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

    demo_mode = args.demo if args.demo is not None else bool(cfg.get("demo", bool(os.environ.get("HFLOCK_DEMO"))))
    token = token or ("demo-secret" if demo_mode else None)

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
