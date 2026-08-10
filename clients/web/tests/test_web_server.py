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
    web_server = ThreadingHTTPServer(("127.0.0.1", 0), OfficeHandler)
    web_server.api_base = "http://127.0.0.1:8080"
    web_server.session_host = "127.0.0.1"
    web_server.session_port = dummy_session_port
    web_server.api_token = "test-secret-token"
    web_server.client_name = "web"
    web_server.demo_mode = False
    web_port = web_server.server_address[1]

    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()

    try:
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

        resp_file = sock.makefile("rb", buffering=0)
        status_line = resp_file.readline().decode()
        assert "101" in status_line
        while True:
            line = resp_file.readline().decode()
            if not line or line in ("\r\n", "\n"):
                break

        assert DummySessionServer.received_headers.get("Authorization") == "Bearer test-secret-token"

        test_payload = b"ping"
        sock.sendall(test_payload)
        echoed = resp_file.read(4)
        assert echoed == test_payload

        sock.close()
    finally:
        web_server.shutdown()
        web_server.server_close()


def test_demo_mode_responses():
    web_server = ThreadingHTTPServer(("127.0.0.1", 0), OfficeHandler)
    web_server.api_base = "http://127.0.0.1:8080"
    web_server.session_host = "127.0.0.1"
    web_server.session_port = 8081
    web_server.api_token = "demo-secret"
    web_server.client_name = "web"
    web_server.demo_mode = True
    web_port = web_server.server_address[1]

    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()

    try:
        req = urllib.request.Request(f"http://127.0.0.1:{web_port}/client-config")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            assert data["client"] == "web"
            assert data["demo"] is True

        req = urllib.request.Request(f"http://127.0.0.1:{web_port}/api/agents")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            assert "architect" in data["agents"]

        req = urllib.request.Request(f"http://127.0.0.1:{web_port}/api/alerts")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            assert len(data["alerts"]) == 300

        req = urllib.request.Request(f"http://127.0.0.1:{web_port}/api/board")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            architect_board = next(a for a in data["agents"] if a["agent"] == "architect")
            assert "Legacy bare ticket string in todo queue" in architect_board["todo"]

        req = urllib.request.Request(f"http://127.0.0.1:{web_port}/api/alerts/stream")
        with urllib.request.urlopen(req) as resp:
            assert "text/event-stream" in resp.headers.get("Content-Type", "")
            lines = []
            for _ in range(20):
                line = resp.readline().decode()
                lines.append(line)
                if line.startswith(": keepalive"):
                    break
            assert any(l.startswith("id: ") for l in lines)
            assert any(l.startswith(": keepalive") for l in lines)

        req = urllib.request.Request(f"http://127.0.0.1:{web_port}/api/agents/sme-2/messages/stream")
        with urllib.request.urlopen(req) as resp:
            assert "text/event-stream" in resp.headers.get("Content-Type", "")
            lines = [resp.readline().decode() for _ in range(5)]
            assert any(l.startswith("event: message") for l in lines)
    finally:
        web_server.shutdown()
        web_server.server_close()


def test_proxy_websocket_session_down_returns_502():
    # Pick a port where no session service is running
    sock_unused = socket.socket()
    sock_unused.bind(("127.0.0.1", 0))
    down_port = sock_unused.getsockname()[1]
    sock_unused.close()

    web_server = ThreadingHTTPServer(("127.0.0.1", 0), OfficeHandler)
    web_server.api_base = "http://127.0.0.1:8080"
    web_server.session_host = "127.0.0.1"
    web_server.session_port = down_port
    web_server.api_token = "test-secret-token"
    web_server.client_name = "web"
    web_server.demo_mode = False
    web_port = web_server.server_address[1]

    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()

    try:
        sock = socket.create_connection(("127.0.0.1", web_port), timeout=5)
        request_raw = (
            "GET /session HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n\r\n"
        )
        sock.sendall(request_raw.encode())
        resp_file = sock.makefile("rb", buffering=0)
        status_line = resp_file.readline().decode()
        assert "502" in status_line
        sock.close()
    finally:
        web_server.shutdown()
        web_server.server_close()


def test_proxy_oversized_post_body_returns_413():
    web_server = ThreadingHTTPServer(("127.0.0.1", 0), OfficeHandler)
    web_server.api_base = "http://127.0.0.1:8080"
    web_server.session_host = "127.0.0.1"
    web_server.session_port = 8081
    web_server.api_token = "test-secret-token"
    web_server.client_name = "web"
    web_server.demo_mode = False
    web_port = web_server.server_address[1]

    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()

    try:
        sock = socket.create_connection(("127.0.0.1", web_port), timeout=5)
        # Send POST headers with oversized Content-Length (10MB)
        request_raw = (
            "POST /api/agents/sme-2/envelopes HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: 10485760\r\n\r\n"
        )
        sock.sendall(request_raw.encode())
        resp_file = sock.makefile("rb", buffering=0)
        status_line = resp_file.readline().decode()
        assert "413" in status_line
        sock.close()
    finally:
        web_server.shutdown()
        web_server.server_close()


def test_proxy_websocket_max_sessions_limit_returns_503():
    web_server = ThreadingHTTPServer(("127.0.0.1", 0), OfficeHandler)
    web_server.api_base = "http://127.0.0.1:8080"
    web_server.session_host = "127.0.0.1"
    web_server.session_port = 8081
    web_server.api_token = "test-secret-token"
    web_server.client_name = "web"
    web_server.demo_mode = False
    web_server.max_sessions = 1
    web_server.active_sessions = 1
    web_server.sessions_lock = threading.Lock()
    web_port = web_server.server_address[1]

    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()

    try:
        sock = socket.create_connection(("127.0.0.1", web_port), timeout=5)
        request_raw = (
            "GET /session HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n\r\n"
        )
        sock.sendall(request_raw.encode())
        resp_file = sock.makefile("rb", buffering=0)
        status_line = resp_file.readline().decode()
        assert "503" in status_line
        sock.close()
    finally:
        web_server.shutdown()
        web_server.server_close()


def test_refuse_non_loopback_without_secret(monkeypatch):
    from clients.web.server import main
    monkeypatch.setattr("sys.argv", ["server.py", "--listen", "0.0.0.0", "--demo"])
    monkeypatch.setenv("HFLOCK_SECRET", "")
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


def test_auth_secret_enforcement_and_login_flow():
    web_server = ThreadingHTTPServer(("127.0.0.1", 0), OfficeHandler)
    web_server.api_base = "http://127.0.0.1:8080"
    web_server.session_host = "127.0.0.1"
    web_server.session_port = 8081
    web_server.api_token = "test-secret-token"
    web_server.client_name = "web"
    web_server.demo_mode = True
    web_server.secret = "topsecret123"
    web_server.valid_sessions = {}
    web_server.max_sessions = 16
    web_server.active_sessions = 0
    web_server.sessions_lock = threading.Lock()
    web_port = web_server.server_address[1]

    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()

    try:
        # 1. Unauthenticated API GET returns 401
        req = urllib.request.Request(f"http://127.0.0.1:{web_port}/api/agents")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 401

        # 2. Unauthenticated WebSocket upgrade returns 401
        sock = socket.create_connection(("127.0.0.1", web_port), timeout=5)
        request_raw = (
            "GET /session HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n\r\n"
        )
        sock.sendall(request_raw.encode())
        resp_file = sock.makefile("rb", buffering=0)
        status_line = resp_file.readline().decode()
        assert "401" in status_line
        sock.close()

        # 3. Invalid login returns 401
        req_bad_login = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/login",
            data=json.dumps({"secret": "wrongsecret"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_bad_login)
        assert exc_info.value.code == 401

        # 4. Valid login returns 200 and Set-Cookie
        req_login = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/login",
            data=json.dumps({"secret": "topsecret123"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_login) as resp:
            assert resp.status == 200
            cookie_header = resp.headers.get("Set-Cookie")
            assert "hflock_session=" in cookie_header
            assert "HttpOnly" in cookie_header
            assert "SameSite=Strict" in cookie_header
            session_cookie = cookie_header.split(";")[0]

        # 5. Authenticated API GET with cookie returns 200
        req_auth = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/api/agents",
            headers={"Cookie": session_cookie},
        )
        with urllib.request.urlopen(req_auth) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert "architect" in data["agents"]

        # 6. Logout clears session cookie
        req_logout = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/logout",
            headers={"Cookie": session_cookie},
            method="POST",
        )
        with urllib.request.urlopen(req_logout) as resp:
            assert resp.status == 200

        # 7. Subsequent request without valid session returns 401
        req_after_logout = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/api/agents",
            headers={"Cookie": session_cookie},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_after_logout)
        assert exc_info.value.code == 401
    finally:
        web_server.shutdown()
        web_server.server_close()


def test_auth_login_rate_limiting_returns_429():
    web_server = ThreadingHTTPServer(("127.0.0.1", 0), OfficeHandler)
    web_server.api_base = "http://127.0.0.1:8080"
    web_server.session_host = "127.0.0.1"
    web_server.session_port = 8081
    web_server.api_token = "test-secret-token"
    web_server.client_name = "web"
    web_server.demo_mode = True
    web_server.secret = "topsecret123"
    web_server.valid_sessions = {}
    web_server.session_ttl = 86400
    web_server.login_attempts = {}
    web_server.max_login_attempts = 3
    web_server.rate_limit_window = 60
    web_server.max_sessions = 16
    web_server.active_sessions = 0
    web_server.sessions_lock = threading.Lock()
    web_port = web_server.server_address[1]

    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()

    try:
        req_bad = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/login",
            data=json.dumps({"secret": "wrongsecret"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        # Fail 3 times
        for _ in range(3):
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(req_bad)
            assert exc_info.value.code == 401

        # 4th attempt returns 429 Too Many Requests
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_bad)
        assert exc_info.value.code == 429
        assert exc_info.value.headers.get("Retry-After") == "60"
    finally:
        web_server.shutdown()
        web_server.server_close()


def test_auth_session_ttl_expiry():
    web_server = ThreadingHTTPServer(("127.0.0.1", 0), OfficeHandler)
    web_server.api_base = "http://127.0.0.1:8080"
    web_server.session_host = "127.0.0.1"
    web_server.session_port = 8081
    web_server.api_token = "test-secret-token"
    web_server.client_name = "web"
    web_server.demo_mode = True
    web_server.secret = "topsecret123"
    # Seed an expired session token (created 100 seconds ago, with a TTL of 10 seconds)
    web_server.valid_sessions = {"expired-token-123": time.time() - 100}
    web_server.session_ttl = 10
    web_server.login_attempts = {}
    web_server.max_login_attempts = 5
    web_server.rate_limit_window = 60
    web_server.max_sessions = 16
    web_server.active_sessions = 0
    web_server.sessions_lock = threading.Lock()
    web_port = web_server.server_address[1]

    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()

    try:
        # Request with expired session cookie should be rejected with 401
        req_exp = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/api/agents",
            headers={"Cookie": "hflock_session=expired-token-123"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_exp)
        assert exc_info.value.code == 401
        assert "expired-token-123" not in web_server.valid_sessions
    finally:
        web_server.shutdown()
        web_server.server_close()

