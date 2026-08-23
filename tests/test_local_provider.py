"""h-flock states the provider intent; the base image translates it.

⚠ **These used to assert `ANTHROPIC_BASE_URL`, the three model tiers and the
`-u` stripping.** All three moved to `startAgent` on 2026-08-23, because they are
CLI knowledge rather than anything about message passing — and because the base
can then REFUSE a CLI that cannot honour the request, which h-flock's hand-built
version could not. A codex agent carrying a provider used to run against the
vendor while `setup.sh` printed `(local)` beside its name.

So what is tested here is the handoff: the right variables, carrying the right
values, and nothing invented. What `startAgent` does with them is base's to test.
"""
from flock.tmux.ops import window_env


def _env(**provider):
    return window_env("dave", cwd="/workdir/dave", provider=provider or None)


def test_no_provider_means_no_provider_variables():
    env = window_env("dave", cwd="/workdir/dave")
    assert not [v for v in env if v.startswith("AGENT_PROVIDER_")]


def test_the_url_is_passed_through_for_the_base_to_normalise():
    """⚠ h-flock does NOT strip `/v1` any more — `startAgent` does, per CLI.

    claude wants the URL without it and codex wants it with, which is exactly
    the asymmetry that should live in one place rather than in every caller.
    """
    env = _env(url="http://10.0.0.5:8000/", model="m")
    assert "AGENT_PROVIDER_URL=http://10.0.0.5:8000" in env


def test_model_and_small_model_are_separate_when_given():
    env = _env(url="http://x:8000", model="big", small_model="small")
    assert "AGENT_PROVIDER_MODEL=big" in env
    assert "AGENT_PROVIDER_SMALL_MODEL=small" in env


def test_small_model_is_omitted_rather_than_duplicated():
    """Absent means absent. The base decides what to fall back to."""
    env = _env(url="http://x:8000", model="big")
    assert "AGENT_PROVIDER_MODEL=big" in env
    assert not [v for v in env if v.startswith("AGENT_PROVIDER_SMALL_MODEL")]


def test_a_supplied_token_is_passed_verbatim():
    env = _env(url="http://x:8000", model="m", token="s3cret")
    assert "AGENT_PROVIDER_TOKEN=s3cret" in env


def test_no_token_means_no_variable_not_a_placeholder():
    """⚠ h-flock used to send the literal `local` when no token was given.

    claude refuses to start without one, but inventing the placeholder is the
    base's call now — it knows which CLI needs a stand-in and which does not.
    """
    env = _env(url="http://x:8000", model="m")
    assert not [v for v in env if v.startswith("AGENT_PROVIDER_TOKEN")]


def test_h_flock_no_longer_sets_anthropic_variables_itself():
    """⚠ THE REGRESSION GUARD FOR THE DELEGATION.

    Setting these here would silently take precedence over whatever `startAgent`
    works out, and would restore the defect this change removed: a CLI that
    cannot honour a provider starting anyway, against the vendor.
    """
    env = _env(url="http://x:8000", model="m", token="t")
    leaked = [v for v in env if "ANTHROPIC_" in v]
    assert not leaked, f"h-flock is still setting CLI variables directly: {leaked}"


def test_provider_and_profile_coexist():
    env = window_env("dave", cwd="/workdir/dave", profile="work",
                     provider={"url": "http://x:8000", "model": "m"})
    assert "CLAUDE_CONFIG_DIR=/home/ubuntu/.claude-work" in env
    assert "AGENT_PROVIDER_URL=http://x:8000" in env


def test_the_token_injected_is_the_one_for_that_agents_profile(monkeypatch):
    """⚠ Two accounts must not receive each other's credential.

    A token in the container environment is inherited by every window — a
    single-account mechanism. Keyed to the profile, agent B never has account
    A's token in its own environment.
    """
    monkeypatch.setenv("CLAUDE_OAUTH_TOKEN_WORK", "tok-work")
    monkeypatch.setenv("CLAUDE_OAUTH_TOKEN_PERSONAL", "tok-personal")

    work = window_env("a", cwd="/workdir/a", profile="work")
    personal = window_env("b", cwd="/workdir/b", profile="personal")

    assert "CLAUDE_CODE_OAUTH_TOKEN=tok-work" in work
    assert "CLAUDE_CODE_OAUTH_TOKEN=tok-personal" in personal
    assert "tok-personal" not in " ".join(work)
    assert "tok-work" not in " ".join(personal)


def test_an_unprofiled_agent_gets_the_default_accounts_token(monkeypatch):
    monkeypatch.setenv("CLAUDE_OAUTH_TOKEN_DEFAULT", "tok-default")
    env = window_env("a", cwd="/workdir/a")
    assert "CLAUDE_CODE_OAUTH_TOKEN=tok-default" in env


def test_a_hyphenated_profile_maps_to_an_underscored_variable(monkeypatch):
    """`account-2` is a legal profile name; `CLAUDE_OAUTH_TOKEN_ACCOUNT-2` is not
    a legal shell variable."""
    monkeypatch.setenv("CLAUDE_OAUTH_TOKEN_ACCOUNT_2", "tok-2")
    env = window_env("a", cwd="/workdir/a", profile="account-2")
    assert "CLAUDE_CODE_OAUTH_TOKEN=tok-2" in env


def test_no_token_means_the_variable_is_absent_not_empty(monkeypatch):
    """⚠ Absent and empty are different to the CLI.

    An empty CLAUDE_CODE_OAUTH_TOKEN looks like a credential that fails; absent
    means log in interactively, which is the path that already works.
    """
    monkeypatch.delenv("CLAUDE_OAUTH_TOKEN_WORK", raising=False)
    monkeypatch.setenv("CLAUDE_OAUTH_TOKEN_WORK", "")
    env = window_env("a", cwd="/workdir/a", profile="work")
    assert not [v for v in env if v.startswith("CLAUDE_CODE_OAUTH_TOKEN")]
