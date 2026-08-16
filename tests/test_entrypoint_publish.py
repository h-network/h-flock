"""The entrypoint judges exposure, because the doors cannot.

⚠ A bind is not an exposure. Both doors bind 0.0.0.0 *inside* the container by
design, so a bind-based refusal fires on every container that has ever run —
which is exactly what it did: build 36 shipped one and the tenant crash-looped
on `SESSION_TLS_CERT … is required when SESSION_BIND is not loopback`. What
decides whether plaintext leaves the machine is the port mapping, and only the
entrypoint is told that.
"""

import os
import subprocess

BASE = {
    "POD": "acme",
    "TENANT": "hq",
    "AGENTS": "architect:tmux",
    "API_TOKEN": "testtoken",
    "TMUX_TMPDIR": "/tmp/test-tmux-publish",
}
REFUSAL = "published on '0.0.0.0' without TLS"


def _run(**overrides):
    env = dict(os.environ)
    env.update(BASE)
    for key in ("API_TLS_CERT", "API_TLS_KEY", "SESSION_TLS_CERT", "SESSION_TLS_KEY",
                "ALLOW_PLAINTEXT_PUBLISH", "API_HOST", "SESSION_HOST", "REDIS_PASSWORD",
                "API_ENABLED"):
        env.pop(key, None)
    env.update({k: v for k, v in overrides.items() if v is not None})
    # The guard runs before anything is started, so a run that gets past it
    # reaches redis and then has to be stopped — refusing after building the
    # whole tenant would be both wasteful and confusing.
    return subprocess.run(
        ["timeout", "6", "bash", "container/entrypoint.sh"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120,
    )


def test_public_publication_without_tls_refuses():
    proc = _run(API_ENABLED="1", API_HOST="0.0.0.0")
    assert proc.returncode != 0
    assert REFUSAL in proc.stderr
    assert "ALLOW_PLAINTEXT_PUBLISH=1" in proc.stderr  # says how to accept it


def test_each_door_is_judged_separately():
    """Publishing one door and not the other is a supported shape (compose §3)."""
    proc = _run(API_HOST="127.0.0.1", SESSION_HOST="0.0.0.0")
    assert proc.returncode != 0
    assert "the session door" in proc.stderr


def test_refusal_happens_before_anything_starts():
    proc = _run(API_ENABLED="1", API_HOST="0.0.0.0")
    assert "redis pid" not in proc.stdout


def test_disabled_api_door_is_not_judged():
    """A door that is never started cannot leak a token, so it is not judged.

    ⚠ Without this the opt-in default would be a silent trap: API_HOST would
    keep its old meaning in `.env`, and a tenant that never runs an api door
    would refuse to start over a token it never serves.
    """
    proc = _run(API_HOST="0.0.0.0")          # API_ENABLED unset -> off
    assert REFUSAL not in proc.stderr


def test_disabled_api_door_says_so():
    """Off must be visible in the log, or 'why is nothing listening' is a hunt."""
    proc = _run()
    assert '"event":"api_disabled"' in proc.stdout


def test_acknowledged_plaintext_starts():
    proc = _run(API_HOST="0.0.0.0", ALLOW_PLAINTEXT_PUBLISH="1")
    assert REFUSAL not in proc.stderr
    assert "redis pid" in proc.stdout


def test_tls_configured_starts():
    proc = _run(API_HOST="0.0.0.0", SESSION_HOST="0.0.0.0",
                API_TLS_CERT="/cert.pem", API_TLS_KEY="/key.pem")
    assert REFUSAL not in proc.stderr
    assert "redis pid" in proc.stdout


def test_unpublished_container_starts():
    """No API_HOST at all is `docker run` with no -p — published nowhere."""
    proc = _run()
    assert REFUSAL not in proc.stderr
    assert "redis pid" in proc.stdout
