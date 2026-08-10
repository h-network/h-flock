"""Build 34: two failures that used to be invisible."""

import os
import stat

from flock.tmux.ops import ensure_claude_project_trusted, write_agent_guide


def test_trust_seeding_failure_is_recorded_not_swallowed(tmp_path, monkeypatch, capsys):
    # ⚠ Force the failure rather than trust the happy path: an unwritable home is
    # exactly the shape of the profile-blind bug, which failed silently while
    # every agent sat at a picker.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    config = home / ".claude.json"
    config.write_text("{}")
    # ⚠ The FILE must be unwritable, not the directory: modifying an existing
    # file does not need write permission on its parent, so a read-only
    # directory does not force this failure.
    config.chmod(stat.S_IRUSR)
    try:
        ensure_claude_project_trusted(str(tmp_path / "workdir"))
        out = capsys.readouterr().out
        assert "claude trust seeding failed" in out
        assert str(tmp_path / "workdir") in out
    finally:
        config.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_trust_seeding_never_raises(tmp_path, monkeypatch):
    # The original decision stands: this must not break a delivery.
    monkeypatch.setenv("HOME", "/nonexistent/nowhere")
    ensure_claude_project_trusted(str(tmp_path))


def test_guide_write_failure_is_recorded(tmp_path, capsys):
    # A path that cannot be created.
    write_agent_guide("/proc/nope/agent", "sme-9")
    assert "guide write failed" in capsys.readouterr().out
