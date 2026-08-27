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


def test_entrypoint_seeds_canonical_accounts_before_unsetting_startup_env():
    script = Path("container/entrypoint.sh").read_text()
    seed = script.index('accounts_key="pod:${POD}:tenant:${TENANT}:accounts"')
    unset = script.index("unset AGENT_CLIS AGENT_PROFILES AGENT_PROVIDERS FLOCK_ACCOUNTS")
    assert seed < unset
    assert 'rcli SADD "$accounts_key" "$_account"' in script


def test_setup_persists_complete_account_list_even_for_single_account():
    script = Path("setup.sh").read_text()
    assert 'echo "FLOCK_ACCOUNTS=$(IFS=,; echo "${PROFILES[*]}")"' in script
    assert 'echo "FLOCK_ACCOUNTS=default"' in script


def test_entrypoint_refuses_invalid_tenant_format(tmp_path):
    env = dict(os.environ)
    env.update(
        POD="acme",
        TENANT="h-EF",  # uppercase
        AGENTS="architect:tmux",
        API_TOKEN="testtoken",
        TMUX_TMPDIR=str(tmp_path / "tmux"),
        FLOCK_CUSTODY_FILE=str(tmp_path / "custody.jsonl"),
    )
    proc = subprocess.run(
        ["bash", "container/entrypoint.sh"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "entrypoint: TENANT must be lowercase alphanumeric/hyphens" in proc.stderr


def test_entrypoint_refuses_reserved_or_all_digit_tenant(tmp_path):
    env = dict(os.environ)
    env.update(
        POD="acme",
        TENANT="123",  # all digits
        AGENTS="architect:tmux",
        API_TOKEN="testtoken",
        TMUX_TMPDIR=str(tmp_path / "tmux"),
        FLOCK_CUSTODY_FILE=str(tmp_path / "custody.jsonl"),
    )
    proc = subprocess.run(
        ["bash", "container/entrypoint.sh"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "entrypoint: TENANT cannot be all digits" in proc.stderr

    env["TENANT"] = "tenant"  # reserved
    proc = subprocess.run(
        ["bash", "container/entrypoint.sh"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "entrypoint: TENANT cannot be reserved word 'tenant'" in proc.stderr


def test_entrypoint_refuses_invalid_pod_format(tmp_path):
    env = dict(os.environ)
    env.update(
        POD="AcmePod",  # uppercase
        TENANT="hq",
        AGENTS="architect:tmux",
        API_TOKEN="testtoken",
        TMUX_TMPDIR=str(tmp_path / "tmux"),
        FLOCK_CUSTODY_FILE=str(tmp_path / "custody.jsonl"),
    )
    proc = subprocess.run(
        ["bash", "container/entrypoint.sh"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "entrypoint: POD must be lowercase alphanumeric/hyphens" in proc.stderr


def test_entrypoint_refuses_invalid_agents_format_or_name(tmp_path):
    env = dict(os.environ)
    env.update(
        POD="acme",
        TENANT="hq",
        AGENTS="Architect:tmux",  # uppercase agent name
        API_TOKEN="testtoken",
        TMUX_TMPDIR=str(tmp_path / "tmux"),
        FLOCK_CUSTODY_FILE=str(tmp_path / "custody.jsonl"),
    )
    proc = subprocess.run(
        ["bash", "container/entrypoint.sh"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "entrypoint: AGENTS entry name 'Architect' must be lowercase" in proc.stderr


def test_entrypoint_refuses_unwritable_custody_file(tmp_path):
    unwritable_file = tmp_path / "read_only" / "custody.jsonl"
    env = dict(os.environ)
    env.update(
        POD="acme",
        TENANT="hq",
        AGENTS="architect:tmux",
        API_TOKEN="testtoken",
        TMUX_TMPDIR=str(tmp_path / "tmux"),
        FLOCK_CUSTODY_FILE=str(unwritable_file),
    )
    # Simulate an environment where sudo is unavailable and directory cannot be written
    proc = subprocess.run(
        ["bash", "-c", "sudo() { return 1; }; export -f sudo 2>/dev/null || true; PATH=/usr/bin:/bin bash container/entrypoint.sh"],
        env=env,
        capture_output=True,
        text=True,
    )
    # Should fail fast on custody file permissions
    assert proc.returncode != 0

