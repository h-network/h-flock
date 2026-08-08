import tomllib
from pathlib import Path

import pytest

from flock.control import cli


@pytest.mark.parametrize(
    ("command", "name"),
    [
        (cli.hire_main, "hire"),
        (cli.let_go_main, "letGo"),
        (cli.pause_main, "pause"),
        (cli.resume_main, "resume"),
    ],
)
def test_help_needs_no_environment_or_redis(monkeypatch, capsys, command, name):
    for key in ("POD", "TENANT", "TMUX_SESSION", "TMUX_SOCKET", "AGENT_NAME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        cli.redis.Redis,
        "from_url",
        lambda url: pytest.fail("help must not connect to Redis"),
    )
    with pytest.raises(SystemExit) as exc:
        command(["--help"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith(f"usage: {name}")


def test_hire_calls_start_opener_and_shared_tmux(monkeypatch):
    calls = []
    fake_redis = object()
    monkeypatch.setenv("POD", "acme")
    monkeypatch.setenv("TENANT", "hq")
    monkeypatch.setenv("TMUX_SESSION", "office")
    monkeypatch.setenv("TMUX_SOCKET", "/tmp/flock.sock")
    monkeypatch.setattr(cli.redis.Redis, "from_url", lambda url: calls.append(("redis", url)) or fake_redis)
    monkeypatch.setattr(
        cli,
        "create_window",
        lambda *args, **kwargs: calls.append(("create_window", args, kwargs)) or (0, "", ""),
    )

    def fake_start(r, **kwargs):
        calls.append(("start_agent", r, kwargs))
        payload = kwargs["envelope"]["payload"]
        kwargs["create_window"](payload["agent"], payload["cli"])

    monkeypatch.setattr(cli, "start_agent", fake_start)
    cli.hire_main(["dave", "--cli", "codex"])

    assert calls[0] == ("redis", "redis://127.0.0.1:6379/0")
    assert calls[1][0:2] == ("start_agent", fake_redis)
    assert calls[1][2]["pod"] == "acme"
    assert calls[1][2]["tenant"] == "hq"
    assert calls[1][2]["envelope"] == {"payload": {"agent": "dave", "cli": "codex"}}
    assert calls[2] == (
        "create_window",
        ("office", "dave"),
        {"command": ["env", "AGENT_NAME=dave", "codex"], "socket": "/tmp/flock.sock"},
    )


def test_hire_defaults_to_claude_and_has_no_profile_option(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli.redis.Redis, "from_url", lambda url: object())
    monkeypatch.setattr(cli, "start_agent", lambda r, **kwargs: captured.update(kwargs))
    cli.hire_main(["dave"])
    assert captured["envelope"]["payload"] == {"agent": "dave", "cli": "claude"}

    with pytest.raises(SystemExit) as exc:
        cli.hire_main(["dave", "--profile", "work"])
    assert exc.value.code == 2


def test_let_go_calls_stop_opener_and_shared_tmux(monkeypatch):
    calls = []
    fake_redis = object()
    monkeypatch.setenv("POD", "acme")
    monkeypatch.setenv("TENANT", "hq")
    monkeypatch.setattr(cli.redis.Redis, "from_url", lambda url: fake_redis)
    monkeypatch.setattr(
        cli,
        "kill_window",
        lambda *args, **kwargs: calls.append(("kill_window", args, kwargs)) or (0, "", ""),
    )

    def fake_stop(r, **kwargs):
        calls.append(("stop_agent", r, kwargs))
        kwargs["kill_window"](kwargs["envelope"]["payload"]["agent"])

    monkeypatch.setattr(cli, "stop_agent", fake_stop)
    cli.let_go_main(["dave"])
    assert calls[0][0:2] == ("stop_agent", fake_redis)
    assert calls[0][2]["envelope"] == {"payload": {"agent": "dave"}}
    assert calls[1] == ("kill_window", ("hq", "dave"), {"socket": None})


@pytest.mark.parametrize(
    ("command", "opener_name", "callback_name", "expected_keys"),
    [
        (cli.pause_main, "pause_agent", "interrupt_window", ("send-keys", "-t", "hq:backend", "C-c")),
        (
            cli.resume_main,
            "resume_agent",
            "resume_window",
            ("send-keys", "-t", "hq:backend", "startAgent --resume", "Enter"),
        ),
    ],
)
def test_pause_resume_call_openers_and_shared_tmux(
    monkeypatch, command, opener_name, callback_name, expected_keys
):
    calls = []
    fake_redis = object()
    monkeypatch.setenv("POD", "acme")
    monkeypatch.setenv("TENANT", "hq")
    monkeypatch.setattr(cli.redis.Redis, "from_url", lambda url: fake_redis)
    monkeypatch.setattr(
        cli,
        "run_tmux",
        lambda *args, **kwargs: calls.append((args, kwargs)) or (0, "", ""),
    )
    monkeypatch.setattr(cli.subprocess, "Popen", lambda args: calls.append(("kick", args)))

    def fake_opener(r, **kwargs):
        assert r is fake_redis
        assert kwargs["pod"] == "acme"
        assert kwargs["tenant"] == "hq"
        assert kwargs["envelope"] == {"payload": {"agent": "backend"}}
        kwargs[callback_name]("backend")
        if callback_name == "resume_window":
            kwargs["kick_agent"]("backend")

    monkeypatch.setattr(cli, opener_name, fake_opener)
    command(["backend"])
    expected = [(expected_keys, {"socket": None})]
    if callback_name == "resume_window":
        expected.append(("kick", ["flock.adapter", "backend"]))
    assert calls == expected


def test_only_non_conflicting_control_scripts_are_installed():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    scripts = pyproject["project"]["scripts"]
    assert scripts["hire"] == "flock.control.cli:hire_main"
    assert scripts["letGo"] == "flock.control.cli:let_go_main"
    assert scripts["pause"] == "flock.control.cli:pause_main"
    assert scripts["resume"] == "flock.control.cli:resume_main"
    assert "startAgent" not in scripts
