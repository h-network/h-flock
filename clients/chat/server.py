#!/usr/bin/env python3
"""chat — a dedicated window for talking to one agent. Nothing else.

    API_TOKEN=… python3 clients/chat/server.py --agent architect --port 8093

⚠ This is NOT the console. The console watches an office; this talks to one
agent. It is the Telegram client's job in a browser window, and it exists
because a conversation is the product and a terminal is not.

It is a **participant**, the same as any app someone else writes: it enrols
itself on the api, sends envelopes, and reads its own mailbox for replies.
It never touches :8081 and never parses a terminal.

Same-origin proxy for the same two reasons as the console: h-flock sends no
CORS headers, and browser EventSource cannot attach a bearer token. The token
stays here and never reaches the page.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent


class ChatHandler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE), **kw)

    def log_message(self, fmt, *args):  # quieter than the stock handler
        pass

    def _json(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _upstream(self, path: str, body: bytes | None = None, stream: bool = False):
        req = urllib.request.Request(
            f"{self.server.api}{path}",
            data=body,
            method="POST" if body is not None else "GET",
        )
        req.add_header("Authorization", f"Bearer {self.server.token}")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if last := self.headers.get("Last-Event-ID"):
            req.add_header("Last-Event-ID", last)
        return urllib.request.urlopen(req, timeout=None if stream else 30)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
            return super().do_GET()
        if self.path == "/config":
            return self._json(200, {"agent": self.server.agent, "client": self.server.client})
        if self.path.startswith("/api/"):
            upstream = self.path[4:]
            # SSE is proxied byte for byte so the browser sees a live stream.
            if "/stream" in upstream:
                try:
                    resp = self._upstream(upstream, stream=True)
                except urllib.error.HTTPError as exc:
                    return self._json(exc.code, {"detail": exc.reason})
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    while chunk := resp.readline():
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            try:
                resp = self._upstream(upstream)
                payload = resp.read()
            except urllib.error.HTTPError as exc:
                return self._json(exc.code, {"detail": exc.reason})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        return super().do_GET()

    def do_POST(self) -> None:
        if not self.path.startswith("/api/"):
            return self._json(404, {"detail": "not found"})
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        try:
            resp = self._upstream(self.path[4:], body=body)
            payload = resp.read()
            code = resp.status
        except urllib.error.HTTPError as exc:
            return self._json(exc.code, {"detail": exc.reason})
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def enrol(api: str, token: str, client: str) -> None:
    """Take a name on the bus. Idempotent — StartAgent on an existing row is fine."""
    body = json.dumps({"kind": "StartAgent", "payload": {"agent": client, "vab": "api"}}).encode()
    req = urllib.request.Request(f"{api}/agents/host/envelopes", data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except urllib.error.HTTPError as exc:
        if exc.code != 409:
            raise


def main() -> int:
    ap = argparse.ArgumentParser(description="a dedicated chat window for one agent")
    ap.add_argument("--api", default=os.environ.get("HFLOCK_API", "http://127.0.0.1:8080"))
    ap.add_argument("--agent", default=os.environ.get("CHAT_AGENT", "architect"))
    ap.add_argument("--client", default=os.environ.get("CHAT_CLIENT", "chat"))
    ap.add_argument("--listen", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8093)
    args = ap.parse_args()

    token = os.environ.get("API_TOKEN", "")
    if not token:
        print("API_TOKEN is required", flush=True)
        return 2

    enrol(args.api, token, args.client)
    server = ThreadingHTTPServer((args.listen, args.port), ChatHandler)
    server.api, server.token = args.api.rstrip("/"), token
    server.agent, server.client = args.agent, args.client
    print(f"chat with {args.agent} — http://{args.listen}:{args.port}  (as {args.client})", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
