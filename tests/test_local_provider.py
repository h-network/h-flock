"""An agent can run against a local model instead of the vendor's."""

from flock.tmux.ops import window_env


def test_no_provider_means_the_vendor_and_no_anthropic_vars():
    env = window_env("architect", tenant="hq")
    assert not [v for v in env if v.startswith("ANTHROPIC_")]


def test_provider_strips_v1_and_sets_all_three_tiers():
    env = window_env(
        "lab",
        tenant="hq",
        provider={"url": "http://172.16.0.11:8000/v1", "model": "qwen3-vl-32b"},
    )
    # ⚠ claude appends /v1/messages itself — a base url with /v1 gives /v1/v1.
    assert "ANTHROPIC_BASE_URL=http://172.16.0.11:8000" in env
    # ⚠ All three tiers or the unset ones fall back to real Anthropic names.
    assert "ANTHROPIC_DEFAULT_OPUS_MODEL=qwen3-vl-32b" in env
    assert "ANTHROPIC_DEFAULT_SONNET_MODEL=qwen3-vl-32b" in env
    assert "ANTHROPIC_DEFAULT_HAIKU_MODEL=qwen3-vl-32b" in env
    assert "ANTHROPIC_AUTH_TOKEN=local" in env


def test_inherited_anthropic_vars_are_stripped():
    env = window_env("lab", provider={"url": "http://x", "model": "m"})
    assert env.count("-u") == 5
    assert "ANTHROPIC_API_KEY" in env


def test_a_supplied_token_is_used_verbatim():
    env = window_env("lab", provider={"url": "http://x/v1", "token": "s3cr3t"})
    assert "ANTHROPIC_AUTH_TOKEN=s3cr3t" in env


def test_provider_and_profile_coexist():
    env = window_env("lab", profile="work", provider={"url": "http://x/v1"})
    assert "CLAUDE_CONFIG_DIR=/home/ubuntu/.claude-work" in env
    assert "ANTHROPIC_BASE_URL=http://x" in env
