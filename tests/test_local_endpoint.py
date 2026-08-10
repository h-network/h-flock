"""An agent can run against a local model instead of the vendor's."""

from flock.tmux.ops import window_env


def test_no_endpoint_means_the_vendor_and_no_anthropic_vars():
    env = window_env("architect", tenant="hq")
    assert not [v for v in env if v.startswith("ANTHROPIC_")]


def test_endpoint_sets_base_url_model_and_a_token():
    env = window_env(
        "lab",
        tenant="hq",
        endpoint={"url": "http://172.16.0.11:8000/v1", "model": "qwen3-vl-32b"},
    )
    assert "ANTHROPIC_BASE_URL=http://172.16.0.11:8000/v1" in env
    assert "ANTHROPIC_MODEL=qwen3-vl-32b" in env
    # ⚠ claude refuses to start without a token even when the server ignores it.
    assert "ANTHROPIC_AUTH_TOKEN=local" in env


def test_a_supplied_token_is_used_verbatim():
    env = window_env("lab", endpoint={"url": "http://x/v1", "token": "s3cr3t"})
    assert "ANTHROPIC_AUTH_TOKEN=s3cr3t" in env


def test_endpoint_and_profile_coexist():
    env = window_env("lab", profile="work", endpoint={"url": "http://x/v1"})
    assert "CLAUDE_CONFIG_DIR=/home/ubuntu/.claude-work" in env
    assert "ANTHROPIC_BASE_URL=http://x/v1" in env
