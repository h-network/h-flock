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
        # 1. The public login document loads successfully. A 401 here makes
        # browsers report the only page they are allowed to see as a failure.
        with urllib.request.urlopen(f"http://127.0.0.1:{web_port}/") as resp:
            assert resp.status == 200
            assert b"h-flock Operator Login" in resp.read()

        # 2. Unauthenticated API GET returns 401
        req = urllib.request.Request(f"http://127.0.0.1:{web_port}/api/agents")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 401

        # 3. Unauthenticated WebSocket upgrade returns 401
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

        # 4. Invalid login returns 401
        req_bad_login = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/login",
            data=json.dumps({"secret": "wrongsecret"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_bad_login)
        assert exc_info.value.code == 401

        # 5. Valid login returns 200 and Set-Cookie
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


def test_healthz_and_readyz_endpoints():
    web_server = ThreadingHTTPServer(("127.0.0.1", 0), OfficeHandler)
    web_server.api_base = "http://127.0.0.1:8080"
    web_server.session_host = "127.0.0.1"
    web_server.session_port = 8081
    web_server.api_token = "test-secret-token"
    web_server.client_name = "web"
    web_server.demo_mode = True
    web_port = web_server.server_address[1]

    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()

    try:
        # GET /healthz
        with urllib.request.urlopen(f"http://127.0.0.1:{web_port}/healthz") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["status"] == "ok"

        # GET /readyz
        with urllib.request.urlopen(f"http://127.0.0.1:{web_port}/readyz") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["status"] == "ready"
    finally:
        web_server.shutdown()
        web_server.server_close()


def test_audit_log_records_operator_actions(tmp_path):
    audit_file = tmp_path / "audit.jsonl"
    web_server = ThreadingHTTPServer(("127.0.0.1", 0), OfficeHandler)
    web_server.api_base = "http://127.0.0.1:8080"
    web_server.session_host = "127.0.0.1"
    web_server.session_port = 8081
    web_server.api_token = "test-secret-token"
    web_server.client_name = "web"
    web_server.demo_mode = True
    web_server.secret = "topsecret123"
    web_server.audit_log = str(audit_file)
    web_server.valid_sessions = {}
    web_server.login_attempts = {}
    web_server.sessions_lock = threading.Lock()
    web_port = web_server.server_address[1]

    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()

    try:
        # Login to generate audit entry
        req_login = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/login",
            data=json.dumps({"secret": "topsecret123"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_login) as resp:
            assert resp.status == 200
            session_cookie = resp.headers.get("Set-Cookie").split(";")[0]

        # Post an operator lifecycle action envelope
        req_hire = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/api/agents/host/envelopes",
            data=json.dumps({"kind": "StartAgent", "payload": {"agent": "worker-1"}}).encode(),
            headers={"Content-Type": "application/json", "Cookie": session_cookie},
            method="POST",
        )
        with urllib.request.urlopen(req_hire) as resp:
            assert resp.status == 202

        # Logout
        req_logout = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/logout",
            headers={"Cookie": session_cookie},
            method="POST",
        )
        with urllib.request.urlopen(req_logout) as resp:
            assert resp.status == 200

        # Verify audit log content
        lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
        records = [json.loads(line) for line in lines]
        events = [r["event"] for r in records]
        assert "login_success" in events
        assert "operator_action" in events
        assert "logout" in events
    finally:
        web_server.shutdown()
        web_server.server_close()


def test_config_file_loading_and_overrides(tmp_path, monkeypatch):
    from clients.web.server import _load_config_file
    cfg_file = tmp_path / "console.json"
    cfg_file.write_text(json.dumps({
        "listen": "127.0.0.1",
        "port": 9090,
        "secret": "myconfigsecret",
        "demo": True,
    }))

    loaded = _load_config_file(str(cfg_file))
    assert loaded["listen"] == "127.0.0.1"
    assert loaded["port"] == 9090
    assert loaded["secret"] == "myconfigsecret"
    assert loaded["demo"] is True


def test_audit_log_rotation(tmp_path):
    audit_file = tmp_path / "audit.jsonl"
    web_server = ThreadingHTTPServer(("127.0.0.1", 0), OfficeHandler)
    web_server.api_base = "http://127.0.0.1:8080"
    web_server.audit_log = str(audit_file)
    web_server.audit_max_bytes = 120  # small byte threshold to trigger rotation
    web_server.audit_max_backups = 3
    web_server.demo_mode = True
    web_server.sessions_lock = threading.Lock()
    web_port = web_server.server_address[1]

    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()

    try:
        for i in range(5):
            req = urllib.request.Request(
                f"http://127.0.0.1:{web_port}/api/agents/host/envelopes",
                data=json.dumps({"kind": "Message", "payload": {"text": f"hello padding string {i}" * 5}}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                assert resp.status == 202

        assert audit_file.exists()
        assert (tmp_path / "audit.jsonl.1").exists()
    finally:
        web_server.shutdown()
        web_server.server_close()


def test_terminal_recordings_endpoints(tmp_path):
    rec_dir = tmp_path / "recordings"
    web_server = ThreadingHTTPServer(("127.0.0.1", 0), OfficeHandler)
    web_server.api_base = "http://127.0.0.1:8080"
    web_server.recordings_dir = str(rec_dir)
    web_server.sessions_lock = threading.Lock()
    web_port = web_server.server_address[1]

    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()

    try:
        # POST /api/recordings to create
        req_post = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/api/recordings",
            data=json.dumps({"agent": "architect"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_post) as resp:
            assert resp.status == 201
            resp_body = json.loads(resp.read().decode())
            rec_id = resp_body["id"]
            assert resp_body["agent"] == "architect"

        # POST /api/recordings/<id>/frames to append frame
        frame_data = {"delta_ms": 140, "direction": "out", "data": "ls -la\n"}
        req_frame = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/api/recordings/{rec_id}/frames",
            data=json.dumps(frame_data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_frame) as resp:
            assert resp.status == 200
            frame_resp = json.loads(resp.read().decode())
            assert frame_resp["status"] == "appended"
            assert frame_resp["frame_count"] == 1

        # GET /api/recordings list
        with urllib.request.urlopen(f"http://127.0.0.1:{web_port}/api/recordings") as resp:
            assert resp.status == 200
            list_body = json.loads(resp.read().decode())
            assert len(list_body) == 1
            assert list_body[0]["id"] == rec_id
            assert list_body[0]["frame_count"] == 1

        # GET /api/recordings/<id> detail
        with urllib.request.urlopen(f"http://127.0.0.1:{web_port}/api/recordings/{rec_id}") as resp:
            assert resp.status == 200
            detail_body = json.loads(resp.read().decode())
            assert detail_body["agent"] == "architect"
            assert len(detail_body["frames"]) == 1
            assert detail_body["frames"][0]["data"] == "ls -la\n"
    finally:
        web_server.shutdown()
        web_server.server_close()


def test_terminal_recordings_retention_and_limits(tmp_path):
    rec_dir = tmp_path / "recordings"
    web_server = ThreadingHTTPServer(("127.0.0.1", 0), OfficeHandler)
    web_server.api_base = "http://127.0.0.1:8080"
    web_server.recordings_dir = str(rec_dir)
    web_server.recording_max_frames = 2
    web_server.recording_max_bytes = 1024
    web_server.sessions_lock = threading.Lock()
    web_port = web_server.server_address[1]

    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()

    try:
        # Create recording
        req_create = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/api/recordings",
            data=json.dumps({"agent": "architect"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_create) as resp:
            rec_id = json.loads(resp.read().decode())["id"]

        # Post frame 1
        req_f1 = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/api/recordings/{rec_id}/frames",
            data=json.dumps({"data": "frame1"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_f1) as resp:
            assert resp.status == 200

        # Post frame 2
        req_f2 = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/api/recordings/{rec_id}/frames",
            data=json.dumps({"data": "frame2"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_f2) as resp:
            assert resp.status == 200

        # Frame 3 exceeds max_recording_frames (2) and returns HTTP 413
        req_f3 = urllib.request.Request(
            f"http://127.0.0.1:{web_port}/api/recordings/{rec_id}/frames",
            data=json.dumps({"data": "frame3"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_f3)
        assert exc_info.value.code == 413
        err_body = json.loads(exc_info.value.read().decode())
        assert err_body.get("truncated") is True

        # Verify recording on disk is explicitly marked truncated
        with urllib.request.urlopen(f"http://127.0.0.1:{web_port}/api/recordings/{rec_id}") as resp:
            rec_obj = json.loads(resp.read().decode())
            assert rec_obj.get("truncated") is True
            assert "truncated_at" in rec_obj
            assert "truncate_reason" in rec_obj
    finally:
        web_server.shutdown()
        web_server.server_close()


def test_audit_read_endpoint_filtering_and_pagination(tmp_path):
    audit_file = tmp_path / "audit.jsonl"
    web_server = ThreadingHTTPServer(("127.0.0.1", 0), OfficeHandler)
    web_server.api_base = "http://127.0.0.1:8080"
    web_server.audit_log = str(audit_file)
    web_server.demo_mode = True
    web_server.sessions_lock = threading.Lock()
    web_port = web_server.server_address[1]

    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()

    try:
        # Generate some audit entries
        for agent_name in ["architect", "sme-2", "architect"]:
            req = urllib.request.Request(
                f"http://127.0.0.1:{web_port}/api/agents/host/envelopes",
                data=json.dumps({"kind": "StartAgent", "payload": {"agent": agent_name}}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                assert resp.status == 202

        # GET /api/audit (all records)
        with urllib.request.urlopen(f"http://127.0.0.1:{web_port}/api/audit") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["total"] == 3
            assert len(data["records"]) == 3

        # GET /api/audit with limit=2
        with urllib.request.urlopen(f"http://127.0.0.1:{web_port}/api/audit?limit=2") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["total"] == 3
            assert len(data["records"]) == 2

        # GET /api/audit with agent=sme-2 filter
        with urllib.request.urlopen(f"http://127.0.0.1:{web_port}/api/audit?agent=sme-2") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["total"] == 1
            assert "sme-2" in json.dumps(data["records"])
    finally:
        web_server.shutdown()
        web_server.server_close()


def test_demo_websocket_handshake(tmp_path):
    web_server = ThreadingHTTPServer(("127.0.0.1", 0), OfficeHandler)
    web_server.api_base = "http://127.0.0.1:8080"
    web_server.demo_mode = True
    web_server.sessions_lock = threading.Lock()
    web_port = web_server.server_address[1]

    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", web_port))
        req = (
            "GET /session?agent=architect HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{web_port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(req.encode())
        resp_data = sock.recv(4096).decode()
        assert "HTTP/1.1 101 Switching Protocols" in resp_data
        assert "Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=" in resp_data
        sock.close()
    finally:
        web_server.shutdown()
        web_server.server_close()
