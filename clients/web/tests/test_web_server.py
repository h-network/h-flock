"""Tests for clients/web/server.py."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from clients.web.server import OfficeHandler


class DummySessionServer(BaseHTTPRequestHandler):
    received_headers: dict[str, str] = {}
    received_data: list[bytes] = []

    def do_GET(self) -> None:
        DummySessionServer.received_headers = dict(self.headers)
        if self.path.startswith("/session"):
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", "dummy-accept")
            self.end_headers()
            self.wfile.flush()
            # Echo loop
            try:
                while True:
                    data = self.rfile.read(4)
                    if not data:
                        break
                    DummySessionServer.received_data.append(data)
                    self.wfile.write(data)
                    self.wfile.flush()
            except Exception:
                pass
        else:
            self.send_error(404)


@pytest.fixture
def dummy_session_port():
    server = ThreadingHTTPServer(("127.0.0.1", 0), DummySessionServer)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()
    server.server_close()


def test_proxy_websocket_adds_bearer_header(dummy_session_port):
    # Set up web server handler against dummy session server
    web_server = ThreadingHTTPServer(("127.0.0.1", 0), OfficeHandler)
    web_server.api_base = "http://127.0.0.1:8080"
    web_server.session_host = "127.0.0.1"
    web_server.session_port = dummy_session_port
    web_server.api_token = "test-secret-token"
    web_server.client_name = "web"
    web_port = web_server.server_address[1]

    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()

    try:
        # Connect raw socket to web server at /session
        sock = socket.create_connection(("127.0.0.1", web_port), timeout=5)
        request_raw = (
            "GET /session HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request_raw.encode())

        # Read handshake response
        resp_file = sock.makefile("rb", buffering=0)
        status_line = resp_file.readline().decode()
        assert "101" in status_line
        while True:
            line = resp_file.readline().decode()
            if not line or line in ("\r\n", "\n"):
                break

        # Verify Authorization header was attached to dummy session server
        assert DummySessionServer.received_headers.get("Authorization") == "Bearer test-secret-token"

        # Send test data and verify raw echo pass-through
        test_payload = b"ping"
        sock.sendall(test_payload)
        echoed = resp_file.read(4)
        assert echoed == test_payload

        sock.close()
    finally:
        web_server.shutdown()
        web_server.server_close()
