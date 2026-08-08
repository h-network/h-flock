import pytest
from unittest.mock import patch, MagicMock
from flock.tmuxhost.host import TmuxHost


class MockRedis:
    def __init__(self, roster_agents):
        self.roster_agents = set(roster_agents)

    def hkeys(self, key):
        return {a.encode("utf-8") for a in self.roster_agents}

    def smembers(self, key):
        return {a.encode("utf-8") for a in self.roster_agents}


@patch("flock.tmuxhost.host.run_tmux")
def test_tmuxhost_reconciliation(mock_run_tmux):
    # Mock calls:
    # 1. has-session -> 0 (exists)
    # 2. set-option exit-empty
    # 3. set-option window-size
    # 4. set-option history-limit
    # 5. list-windows -> returns "__init__\n"
    # 6. new-window -> returns 0
    # 7. list-windows (second call) -> returns "__init__\nalice\n"
    # 8. kill-window __init__ -> returns 0

    mock_run_tmux.side_effect = [
        (0, "", ""),  # has-session
        (0, "", ""),  # exit-empty
        (0, "", ""),  # window-size
        (0, "", ""),  # history-limit
        (0, "__init__", ""),  # list-windows 1
        (0, "", ""),  # new-window alice
        (0, "__init__\nalice", ""),  # list-windows 2
        (0, "", ""),  # kill-window __init__
    ]

    r = MockRedis(["alice"])
    host = TmuxHost(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")
    host.reconcile_once(r)

    # Check new-window was called for alice
    calls = [c[0] for c in mock_run_tmux.call_args_list]
    assert any("new-window" in c for c in calls)
    assert any("kill-window" in c for c in calls)


@patch("flock.tmuxhost.host.run_tmux")
def test_tmuxhost_ensure_session_with_roster_agent(mock_run_tmux):
    mock_run_tmux.side_effect = [
        (1, "", "no server running"),  # has-session -> 1 (not existing)
        (0, "", ""),  # new-session -d -s hq -n alice ...
        (0, "", ""),  # exit-empty
        (0, "", ""),  # window-size
        (0, "", ""),  # history-limit
        (0, "alice", ""),  # list-windows 1 -> alice
        (0, "alice", ""),  # list-windows 2 -> alice
    ]

    r = MockRedis(["alice"])
    host = TmuxHost(pod="acme", tenant="hq", redis_url="redis://127.0.0.1:6379/0", session_name="hq")
    host.reconcile_once(r)

    calls = [c[0] for c in mock_run_tmux.call_args_list]
    # Check new-session was called with alice as initial window
    assert any("new-session" in c and "alice" in c for c in calls)
    # Check no kill-window was called (as alice is the only window)
    assert not any("kill-window" in c for c in calls)

