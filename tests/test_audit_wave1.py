import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from flock.api.app import Settings, create_app, _stream_response
from flock.session.app import SessionSettings, create_app as create_session_app
from flock.session.control import ControlModeClient, Subscriber, _unescape_control


class FakeRedis:
    def __init__(self, data=None):
        self.data = data or {}
        self._cmd_count = 0

    def smembers(self, key):
        return self.data.get(key, set())

    def hkeys(self, key):
        val = self.data.get(key, {})
        return set(val.keys()) if isinstance(val, dict) else set(val)

    def hgetall(self, key):
        val = self.data.get(key, {})
        return val if isinstance(val, dict) else {}

    def lrange(self, key, start, end):
        self._cmd_count += 1
        return self.data.get(key, [])

    def pipeline(self, transaction=False):
        self._cmd_count = 0
        return self

    def execute(self):
        res = [[] for _ in range(self._cmd_count)]
        self._cmd_count = 0
        return res


def test_row_7_session_control_recovers_after_stream_break(monkeypatch):
    monkeypatch.setenv("TMUX_TMPDIR", "/tmp")
    controller = ControlModeClient("test_session")
    controller.broken_reason = "tmux stream closed"

    with patch.object(controller, "start", new_callable=AsyncMock) as mock_start:
        asyncio.run(controller.ensure_connected())
        mock_start.assert_awaited_once()


def test_row_8_oversized_output_line_subprocess_limit(monkeypatch):
    monkeypatch.setenv("TMUX_TMPDIR", "/tmp")
    controller = ControlModeClient("test_session")
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec, \
         patch.object(controller, "refresh_panes", new_callable=AsyncMock):
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.readline = AsyncMock(side_effect=[b"%end 0\n", b""])
        mock_proc.stderr.readline = AsyncMock(return_value=b"")
        mock_proc.stdin.drain = AsyncMock(return_value=None)
        mock_exec.return_value = mock_proc
        try:
            asyncio.run(controller.start())
        except Exception:
            pass
        assert mock_exec.call_args.kwargs.get("limit") == 16 * 1024 * 1024


def test_row_9_non_ascii_output_decoding():
    # UTF-8 encoded text for "hello ’ world" (contains right single quotation mark U+2019)
    utf8_bytes = "hello ’ world".encode("utf-8")
    unescaped = _unescape_control(utf8_bytes)
    # UTF-8 decoding should preserve the single character ’ instead of 3 latin-1 characters
    decoded = unescaped.decode("utf-8", errors="replace")
    assert decoded == "hello ’ world"
    assert len(decoded) == 13


def test_row_10_slow_viewer_queue_bounded():
    subscriber = Subscriber()
    assert subscriber.queue.maxsize == 1000


def test_row_11_sse_uses_asyncio_to_thread():
    request = MagicMock()
    request.headers = {}
    request.is_disconnected = AsyncMock(side_effect=[False, True])

    with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        mock_to_thread.return_value = []
        response = _stream_response(request, MagicMock(), "key", "event", None, "envelope")

        async def run_gen():
            async for _ in response.body_iterator:
                pass

        asyncio.run(run_gen())
        mock_to_thread.assert_awaited()


def test_row_12_malformed_roster_row_does_not_break_board():
    r = FakeRedis()
    # Roster containing one valid agent "backend" and one invalid agent name "invalid:name"
    r.data["pod:test:tenant:office:roster"] = {b"backend": b"tmux", b"invalid:name": b"tmux"}
    app = create_app(
        settings=Settings(pod="test", tenant="office", api_token="secret"),
        redis_client=r,
    )
    all_boards_route = [route for route in app.routes if getattr(route, "path", None) == "/board"][0]
    res_data = all_boards_route.endpoint()
    assert "agents" in res_data
    agent_names = [b["agent"] for b in res_data["agents"]]
    assert "backend" in agent_names
    assert "invalid:name" not in agent_names


def test_row_13_pane_to_agent_map_handles_duplicate_names():
    controller = ControlModeClient("test_session")

    async def mock_command(*args):
        return ["%0\tbackend", "%1\tbackend"]

    controller.command = mock_command
    asyncio.run(controller.refresh_panes())
    assert controller.agent_to_pane["backend"] == "%0"
