import pytest

from flock.openshell.headless import UNVERIFIED_HEADLESS_CLIS, headless_command


def test_claude_fresh_and_resume():
    assert headless_command("claude", resume=False) == ["claude", "-p"]
    assert headless_command("claude", resume=True) == ["claude", "-p", "-c"]


def test_codex_fresh_and_resume():
    assert headless_command("codex", resume=False) == ["codex", "exec", "-"]
    assert headless_command("codex", resume=True) == ["codex", "exec", "resume", "--last", "-"]


def test_unknown_cli_raises_instead_of_guessing():
    with pytest.raises(ValueError):
        headless_command("some-future-cli", resume=False)


def test_agy_is_flagged_unverified():
    assert "agy" in UNVERIFIED_HEADLESS_CLIS
    # Still returns something rather than raising, but callers are expected
    # to check UNVERIFIED_HEADLESS_CLIS and treat this branch with suspicion.
    assert headless_command("agy", resume=False) == ["agy", "-p"]
