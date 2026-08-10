#!/usr/bin/env python3
"""Serve the dependency-free office UI and proxy one h-flock tenant."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


HERE = Path(__file__).resolve().parent


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def do_GET(self) -> None:
        if self.path == "/client-config":
            self._json(200, {"client": self.server.client_name, "demo": self.server.demo_mode})
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
        if self.server.demo_mode and self.path.startswith("/api/"):
            self._demo_api()
        elif self.path.startswith("/api/"):
            self._proxy()
        else:
            self.send_error(404)

    def _proxy(self) -> None:
        target = self.server.api_base + self.path.removeprefix("/api")
        length = int(self.headers.get("Content-Length", "0"))
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

        t1 = threading.Thread(target=forward, args=(client_sock, upstream_sock), daemon=True)
        t2 = threading.Thread(target=forward, args=(upstream_sock, client_sock), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    def _demo_api(self) -> None:
        subpath = self.path.removeprefix("/api")
        if subpath == "/agents":
            self._json(200, {"agents": ["architect", "sme-2", "sme-3", "lab"]})
        elif subpath == "/agents/architect":
            self._json(200, {
                "agent": "architect", "vab": "tmux",
                "depths": {"ingress": 0, "egress": 0, "dead": 0},
                "presence": {"state": "working", "since": "2026-08-10T02:00:00Z", "last_activity": "2026-08-10T02:45:00Z"},
            })
        elif subpath == "/agents/sme-2":
            self._json(200, {
                "agent": "sme-2", "vab": "tmux",
                "depths": {"ingress": 1, "egress": 0, "dead": 0},
                "presence": {"state": "idle", "since": "2026-08-10T02:10:00Z", "last_activity": "2026-08-10T02:30:00Z"},
            })
        elif subpath == "/agents/sme-3":
            self._json(200, {
                "agent": "sme-3", "vab": "tmux",
                "depths": {"ingress": 2, "egress": 0, "dead": 0},
                "presence": {"state": "blocked", "since": "2026-08-10T02:15:00Z", "last_activity": "2026-08-10T02:20:00Z"},
            })
        elif subpath == "/agents/lab":
            self._json(200, {
                "agent": "lab", "vab": "tmux",
                "depths": {"ingress": 0, "egress": 0, "dead": 0},
                "presence": {"state": "unknown", "since": "", "last_activity": ""},
            })
        elif subpath == "/board":
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
        elif subpath == "/alerts":
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
        elif subpath == "/alerts/stream" or subpath.startswith("/alerts/stream"):
            self._demo_sse([
                ("100-0", "alert", {"cursor": "100-0", "ts": "2026-08-10T02:20:00Z", "kind": "stalled", "agent": "sme-3", "doing_age_s": 900}),
                ("101-0", "alert", {"cursor": "101-0", "ts": "2026-08-10T02:25:00Z", "kind": "credential", "account": "claude", "detail": "expired"}),
            ])
        elif subpath.endswith("/activity/stream"):
            self._demo_sse([
                ("act-1", "activity", {"cursor": "act-1", "ts": "2026-08-10T02:30:00Z", "kind": "tool", "tool": "pytest", "agent": "architect"}),
            ])
        elif subpath.endswith("/messages/stream"):
            self._demo_sse([
                ("msg-1", "message", {
                    "cursor": "msg-1",
                    "ts": "2026-08-10T02:35:00Z",
                    "kind": "Message",
                    "producer": "architect",
                    "recipient": "sme-2",
                    "payload": {"text": "Please review Build 33 console UI."},
                }),
            ])
        elif subpath.endswith("/envelopes") and self.command == "POST":
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
    parser.add_argument("--listen", default=os.environ.get("WEB_LISTEN", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("WEB_PORT", "8090")))
    parser.add_argument("--api", default=os.environ.get("HFLOCK_API", "http://127.0.0.1:8080"))
    parser.add_argument("--session", default=os.environ.get("HFLOCK_SESSION", "http://127.0.0.1:8081"))
    parser.add_argument("--token", default=os.environ.get("API_TOKEN"))
    parser.add_argument("--client", default=os.environ.get("HFLOCK_CLIENT", "web"))
    parser.add_argument("--demo", action="store_true", default=bool(os.environ.get("HFLOCK_DEMO")))
    args = parser.parse_args()

    demo_mode = args.demo
    token = args.token or ("demo-secret" if demo_mode else None)
    if not token and not demo_mode:
        parser.error("provide --token or API_TOKEN")

    api_base = args.api.rstrip("/")
    session_host = "127.0.0.1"
    session_port = 8081

    if not demo_mode:
        parsed = urlsplit(args.api)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            parser.error("--api must be an absolute http(s) URL")

        parsed_session = urlsplit(args.session)
        if parsed_session.scheme not in {"http", "https", "ws", "wss"} or not parsed_session.netloc:
            parser.error("--session must be an absolute http(s) or ws(s) URL")
        session_host = parsed_session.hostname or "127.0.0.1"
        session_port = parsed_session.port or 8081

        try:
            enrol(api_base, token, args.client)
        except (urllib.error.URLError, RuntimeError) as error:
            print(f"could not enrol {args.client}: {error}", file=sys.stderr)
            raise SystemExit(1) from error

    server = ThreadingHTTPServer((args.listen, args.port), OfficeHandler)
    server.api_base = api_base
    server.session_host = session_host
    server.session_port = session_port
    server.api_token = token
    server.client_name = args.client
    server.demo_mode = demo_mode
    mode_str = " (DEMO MODE)" if demo_mode else ""
    print(f"office UI: http://{args.listen}:{args.port} (client {args.client}){mode_str}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
