#!/usr/bin/env python3
"""Serve the dependency-free office UI and proxy one h-flock tenant."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


HERE = Path(__file__).resolve().parent


class OfficeHandler(SimpleHTTPRequestHandler):
    server_version = "h-flock-web/1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def do_GET(self) -> None:
        if self.path == "/client-config":
            self._json(200, {"client": self.server.client_name})
        elif self.path == "/" or self.path.startswith("/?"):
            self.path = "/index.html"
            super().do_GET()
        elif self.path.startswith("/api/"):
            self._proxy()
        else:
            super().do_GET()

    def do_POST(self) -> None:
        if self.path.startswith("/api/"):
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
    parser.add_argument("--token", default=os.environ.get("API_TOKEN"))
    parser.add_argument("--client", default=os.environ.get("HFLOCK_CLIENT", "web"))
    args = parser.parse_args()
    if not args.token:
        parser.error("provide --token or API_TOKEN")
    parsed = urlsplit(args.api)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        parser.error("--api must be an absolute http(s) URL")
    api_base = args.api.rstrip("/")
    try:
        enrol(api_base, args.token, args.client)
    except (urllib.error.URLError, RuntimeError) as error:
        print(f"could not enrol {args.client}: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    server = ThreadingHTTPServer((args.listen, args.port), OfficeHandler)
    server.api_base = api_base
    server.api_token = args.token
    server.client_name = args.client
    print(f"office UI: http://{args.listen}:{args.port} (client {args.client})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
