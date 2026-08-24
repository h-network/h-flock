from conftest import FakeRedis as StubRedis
from unittest.mock import patch

import pytest

from flock.port.openers import message_opener
from flock.bus import build as build_envelope
from flock.tmux import TmuxCommandError, create_window, list_windows



@patch("flock.tmux.ops.run_tmux")
def test_list_windows_raises_instead_of_reporting_empty_on_tmux_failure(mock_run_tmux):
    mock_run_tmux.return_value = (1, "", "can't find session: hq")

    with pytest.raises(TmuxCommandError, match="list-windows.*can't find session"):
        list_windows("hq")


@patch("flock.tmux.ops.run_tmux")
def test_create_window_does_not_create_when_window_listing_fails(mock_run_tmux, tmp_path):
    mock_run_tmux.return_value = (1, "", "server unavailable")

    with pytest.raises(TmuxCommandError, match="list-windows.*server unavailable"):
        create_window("hq", "alice", cwd=str(tmp_path / "alice"))

    assert [call.args[0] for call in mock_run_tmux.call_args_list] == ["list-windows"]


@patch("flock.port.openers.list_windows")
@patch("flock.tmux.ops.run_tmux")
def test_message_opener_raises_when_tmux_paste_fails_and_cleans_buffer(mock_run_tmux, mock_list_windows):
    mock_list_windows.return_value = {"bob"}
    mock_run_tmux.side_effect = [
        (0, "", ""),
        (1, "", "can't find pane"),
        (0, "", ""),
    ]
    envelope = build_envelope(kind="Message", source="alice", destination="bob", payload={"text": "hello"})

    with pytest.raises(TmuxCommandError, match="paste-buffer.*can't find pane"):
        message_opener(StubRedis(), pod="acme", tenant="hq", agent="bob", envelope=envelope, session_name="hq")

    assert [call.args[0] for call in mock_run_tmux.call_args_list] == [
        "load-buffer", "paste-buffer", "delete-buffer"
    ]
