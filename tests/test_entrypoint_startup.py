import os
import subprocess
from pathlib import Path

import redis

from flock.bus.connection import local_redis_url


def test_redis_password_reserved_characters_round_trip_through_url_parser():
    password = "p@ss:/?#% word"
    url = local_redis_url(password)

    assert url == "redis://:p%40ss%3A%2F%3F%23%25%20word@127.0.0.1:6379/0"
    assert redis.Redis.from_url(url).connection_pool.connection_kwargs["password"] == password


def test_entrypoint_uses_encoded_redis_url_builder():
    script = Path("container/entrypoint.sh").read_text()
    assert "from flock.bus.connection import local_redis_url" in script
    assert 'redis://:${redis_password}@' not in script


def test_entrypoint_redis_readiness_has_a_deadline(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "python3").write_text("#!/bin/sh\necho 1\n")
    (fake_bin / "redis-server").write_text("#!/bin/sh\nexec sleep 30\n")
    (fake_bin / "redis-cli").write_text("#!/bin/sh\necho LOADING\n")
    for command in fake_bin.iterdir():
        command.chmod(0o755)

    env = dict(os.environ)
    env.update(
        POD="acme",
        TENANT="hq",
        AGENTS="architect:tmux",
        API_TOKEN="testtoken",
        TMUX_TMPDIR=str(tmp_path / "tmux"),
        REDIS_READY_SECONDS="0",
        PATH=f"{fake_bin}:{env['PATH']}",
    )
    proc = subprocess.run(
        ["bash", "container/entrypoint.sh"],
        env=env,
        capture_output=True,
        text=True,
        timeout=3,
    )

    assert proc.returncode != 0
    assert "timed out waiting for Redis readiness" in proc.stderr


def test_entrypoint_configures_redis_aof_persistence():
    script = Path("container/entrypoint.sh").read_text()
    assert "--appendonly yes" in script
    assert "--appendfsync everysec" in script
    assert "from flock.bus.resources import purge_transport" in script

