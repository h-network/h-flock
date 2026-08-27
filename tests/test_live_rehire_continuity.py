"""Live verification test for retiring and re-hiring an agent with session history."""

import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
import redis

from flock.bus import prefix
from flock.control import start_agent, stop_agent
from flock.tmux import run_tmux, list_windows
from flock.tmuxhost.host import TmuxHost


@pytest.fixture
def isolated_env(tmp_path):
    # 1. Real isolated Redis server
    redis_bin = shutil.which("redis-server") or "/usr/bin/redis-server"
    if not Path(redis_bin).exists():
        pytest.fail(f"redis-server binary not found at {redis_bin}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    redis_proc = subprocess.Popen(
        [redis_bin, "--port", str(port), "--dir", str(tmp_path), "--save", "", "--appendonly", "no"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    redis_url = f"redis://127.0.0.1:{port}/0"

    # 2. Isolated tmux socket and Home directory
    tmux_socket = str(tmp_path / "tmux.sock")
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    client = None
    try:
        for _ in range(50):
            try:
                c = redis.Redis(host="127.0.0.1", port=port, decode_responses=True)
                if c.ping():
                    client = c
                    break
            except redis.RedisError:
                time.sleep(0.05)
        if not client:
            pytest.fail("isolated redis-server failed to start")

        yield {
            "client": client,
            "redis_url": redis_url,
            "tmux_socket": tmux_socket,
            "home": home_dir,
            "tmp_path": tmp_path,
        }
    finally:
        # Kill isolated tmux server if running
        subprocess.run(["tmux", "-S", tmux_socket, "kill-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        redis_proc.terminate()
        try:
            redis_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            redis_proc.kill()


def test_live_retire_and_rehire_session_continuity(isolated_env, monkeypatch):
    client = isolated_env["client"]
    redis_url = isolated_env["redis_url"]
    tmux_socket = isolated_env["tmux_socket"]
    home = isolated_env["home"]
    session_name = "test-office"
    agent_name = "test-agent"

    monkeypatch.setenv("HOME", str(home))

    host = TmuxHost(
        pod="acme",
        tenant="hq",
        redis_url=redis_url,
        session_name=session_name,
        socket=tmux_socket,
    )

    # 1. First hire (fresh, no history exists yet)
    start_agent(
        client,
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": agent_name, "cli": "claude"}},
        replace_window=lambda a: None,
    )
    host.reconcile_once(client)

    # Verify window created in isolated tmux
    windows = list_windows(session_name, socket=tmux_socket)
    assert agent_name in windows

    # 2. Simulate agent work: write session file to ~/.claude/projects/-workdir-test-agent/
    proj_dir = home / ".claude" / "projects" / f"-workdir-{agent_name}"
    proj_dir.mkdir(parents=True, exist_ok=True)
    session_file = proj_dir / "session-001.jsonl"
    session_file.write_text('{"type": "message", "text": "previous conversation context"}\n')

    # 3. Retire agent (StopAgent)
    stop_agent(
        client,
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": agent_name}},
        kill_window=lambda a: host.kill_window(a),
    )
    host.reconcile_once(client)

    # Window is gone, roster is empty
    windows_after_stop = list_windows(session_name, socket=tmux_socket)
    assert agent_name not in windows_after_stop
    # Session file survives on filesystem
    assert session_file.exists()

    # 4. Re-hire agent (auto-detect should find prior history and resume!)
    start_agent(
        client,
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": agent_name, "cli": "claude"}},
        replace_window=lambda a: None,
    )
    host.reconcile_once(client)

    # Window created again
    windows_rehire = list_windows(session_name, socket=tmux_socket)
    assert agent_name in windows_rehire

    # 5. Retire and re-hire with explicit --fresh (resume=False)
    stop_agent(
        client,
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": agent_name}},
        kill_window=lambda a: host.kill_window(a),
    )
    host.reconcile_once(client)

    start_agent(
        client,
        pod="acme",
        tenant="hq",
        envelope={"payload": {"agent": agent_name, "cli": "claude", "resume": False}},
        replace_window=lambda a: None,
    )
    host.reconcile_once(client)

    windows_fresh = list_windows(session_name, socket=tmux_socket)
    assert agent_name in windows_fresh
