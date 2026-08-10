import os
import subprocess
import pytest


def test_entrypoint_refuses_widened_redis_bind_without_password():
    env = dict(os.environ)
    env["POD"] = "acme"
    env["TENANT"] = "hq"
    env["AGENTS"] = "architect:tmux"
    env["API_TOKEN"] = "testtoken"
    env["TMUX_TMPDIR"] = "/tmp/test-tmux-entrypoint"
    env["REDIS_BIND"] = "0.0.0.0"
    env.pop("REDIS_PASSWORD", None)

    proc = subprocess.run(
        ["bash", "container/entrypoint.sh"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.returncode != 0
    assert "REDIS_PASSWORD is required when REDIS_BIND is not loopback" in proc.stderr
