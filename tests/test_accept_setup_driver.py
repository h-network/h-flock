import os
import shutil
import subprocess
import tempfile
import pytest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SETUP = ROOT / "setup.sh"
DRIVER = ROOT / "container/drive-setup.py"


def _mock_docker(bin_dir: Path):
    bin_dir.mkdir(parents=True, exist_ok=True)
    docker_script = """#!/bin/sh
case "$1 $2" in
  'inspect --format'*) echo healthy ;;
  *) exit 0 ;;
esac
"""
    (bin_dir / "docker").write_text(docker_script)
    (bin_dir / "docker").chmod(0o755)


def test_setup_bool_and_port_validation(tmp_path):
    """Directly test that setup.sh rejects invalid/shifted inputs for boolean and port prompts."""
    bin_dir = tmp_path / "bin"
    _mock_docker(bin_dir)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    shutil.copy2(SETUP, tmp_path / "setup.sh")
    shutil.copytree(ROOT / "container", tmp_path / "container")
    local_setup = tmp_path / "setup.sh"

    # 1. Invalid boolean string '18080' at 'Use more than one account' prompt
    bad_bool_input = "\n".join(["acme", "hq", "2", "architect", "sme-2", "18080"]) + "\n"
    proc = subprocess.run(
        [str(local_setup)],
        input=bad_bool_input,
        text=True,
        capture_output=True,
        cwd=tmp_path,
        env=env,
    )
    assert proc.returncode == 2
    assert "error: expected yes or no, got '18080'" in proc.stderr

    # 2. Valid boolean inputs ('yes', 'no', blank)
    valid_input = "\n".join([
        "acme", "hq-valid", "2", "architect", "sme-2",
        "no",        # multi-account (no)
        "",          # token
        "",          # default cli
        "",          # cli exceptions
        "no",        # local provider
        "yes",       # api enabled
        "no",        # telegram
        "yes",       # api publish
        "18080",     # api port
        "yes",       # session publish
        "18081",     # session port
        "yes",       # remote
        "",          # tls cert
        "no",        # self-signed
    ]) + "\n"
    proc2 = subprocess.run(
        [str(local_setup)],
        input=valid_input,
        text=True,
        capture_output=True,
        cwd=tmp_path,
        env=env,
    )
    assert "error: expected yes or no" not in proc2.stderr
    assert proc2.returncode == 0


def test_drive_setup_against_real_setup_sh(tmp_path):
    """drive-setup.py drives setup.sh 1:1 through a pty matching all prompts in exact sequence."""
    bin_dir = tmp_path / "bin"
    _mock_docker(bin_dir)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    shutil.copy2(SETUP, tmp_path / "setup.sh")
    shutil.copytree(ROOT / "container", tmp_path / "container")

    cmd = [
        "python3", str(tmp_path / "container/drive-setup.py"),
        "--setup-cmd", str(tmp_path / "setup.sh"),
        "--tenant", "hq-test",
        "--api-port", "19080",
        "--session-port", "19081",
        "--publish-api", "y",
        "--publish-session", "y",
        "--remote", "y",
        "--self-signed", "n",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_path, env=env)
    assert proc.returncode == 0, f"drive-setup failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"

    tenant_dir = tmp_path / "tenants/hq-test"
    tenant_env = tenant_dir / ".env"
    env_content = tenant_env.read_text()
    assert tenant_env.stat().st_mode & 0o777 == 0o600
    assert "API_ENABLED=1" in env_content
    assert "API_PORT=19080" in env_content
    assert "SESSION_PORT=19081" in env_content

    ports_content = (tenant_dir / "compose.ports.yaml").read_text()
    assert "0.0.0.0:19080:8080" in ports_content
    assert "0.0.0.0:19081:8081" in ports_content
    attach = tenant_dir / "attach.sh"
    assert attach.stat().st_mode & 0o111
    assert 'flock_tenant_context "$(basename "$_tenant_dir")"' in attach.read_text()
    assert 'tmux attach -t "$TENANT"' in attach.read_text()


def test_setup_imports_only_matching_legacy_tenant(tmp_path):
    bin_dir = tmp_path / "bin"
    _mock_docker(bin_dir)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    shutil.copy2(SETUP, tmp_path / "setup.sh")
    shutil.copytree(ROOT / "container", tmp_path / "container")

    legacy = "POD=acme\nTENANT=legacy\nAPI_TOKEN=keep-me\n"
    (tmp_path / "container/.env").write_text(legacy)
    ports = "services:\n  tenant:\n    ports:\n      - 127.0.0.1:8080:8080\n"
    (tmp_path / "container/compose.ports.yaml").write_text(ports)

    # Import happens immediately after the tenant prompt; an invalid agent count
    # stops before later setup work can rewrite the imported env.
    matched = subprocess.run(
        [str(tmp_path / "setup.sh")], input="acme\nlegacy\n0\n", text=True,
        capture_output=True, cwd=tmp_path, env=env,
    )
    assert matched.returncode == 2
    assert (tmp_path / "tenants/legacy/.env").read_text() == legacy
    assert (tmp_path / "tenants/legacy/compose.ports.yaml").read_text() == ports
    assert (tmp_path / "container/.env").read_text() == legacy

    mismatched = subprocess.run(
        [str(tmp_path / "setup.sh")], input="acme\nother\n0\n", text=True,
        capture_output=True, cwd=tmp_path, env=env,
    )
    assert mismatched.returncode == 2
    assert not (tmp_path / "tenants/other/.env").exists()
    assert "belongs to 'legacy'; leaving it untouched" in mismatched.stderr


def test_two_setup_runs_keep_tenant_config_isolated(tmp_path):
    bin_dir = tmp_path / "bin"
    _mock_docker(bin_dir)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    shutil.copy2(SETUP, tmp_path / "setup.sh")
    shutil.copytree(ROOT / "container", tmp_path / "container")

    def run(tenant: str, api_port: str, session_port: str):
        return subprocess.run(
            [
                "python3", str(tmp_path / "container/drive-setup.py"),
                "--setup-cmd", str(tmp_path / "setup.sh"),
                "--tenant", tenant,
                "--api-port", api_port,
                "--session-port", session_port,
                "--publish-api", "y", "--publish-session", "y",
                "--remote", "y", "--self-signed", "n",
            ],
            capture_output=True, text=True, cwd=tmp_path, env=env,
        )

    first = run("first", "19180", "19181")
    assert first.returncode == 0, first.stdout + first.stderr
    first_env_before = (tmp_path / "tenants/first/.env").read_text()
    first_ports_before = (tmp_path / "tenants/first/compose.ports.yaml").read_text()

    second = run("second", "19280", "19281")
    assert second.returncode == 0, second.stdout + second.stderr
    assert (tmp_path / "tenants/first/.env").read_text() == first_env_before
    assert (tmp_path / "tenants/first/compose.ports.yaml").read_text() == first_ports_before
    assert "API_PORT=19280" in (tmp_path / "tenants/second/.env").read_text()
    assert "19280:8080" in (tmp_path / "tenants/second/compose.ports.yaml").read_text()


def test_drive_setup_aborts_on_prompt_drift(tmp_path):
    """An inserted prompt is recognized and refused without waiting for timeout."""
    bin_dir = tmp_path / "bin"
    _mock_docker(bin_dir)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    # Create modified setup.sh with an extra prompt inserted
    modified_setup = (SETUP.read_text()).replace(
        'read -rp "Pod name [acme]: "',
        'read -rp "Extra unexpected prompt? [y/N]: "; read -rp "Pod name [acme]: "'
    )
    (tmp_path / "setup.sh").write_text(modified_setup)
    (tmp_path / "setup.sh").chmod(0o755)
    shutil.copytree(ROOT / "container", tmp_path / "container")

    cmd = [
        "python3", str(tmp_path / "container/drive-setup.py"),
        "--setup-cmd", str(tmp_path / "setup.sh"),
        "--tenant", "hq-drift",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_path, env=env)
    assert proc.returncode == 2
    assert "unexpected prompt before prompt #1" in proc.stderr
    assert "Extra unexpected prompt? [y/N]:" in proc.stderr


def test_drive_setup_refuses_omitted_expected_prompt(tmp_path):
    script = tmp_path / "setup.sh"
    script.write_text("#!/bin/sh\nprintf 'Pod name [acme]: '\nread pod\nexit 0\n")
    script.chmod(0o755)

    proc = subprocess.run(
        ["python3", str(DRIVER), "--setup-cmd", str(script)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    assert proc.returncode == 2
    assert "prompt #2" in proc.stderr


def test_drive_setup_refuses_unexpected_trailing_prompt(tmp_path):
    bin_dir = tmp_path / "bin"
    _mock_docker(bin_dir)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    marker = 'echo "wrote tenants/${TENANT}/.env and attach.sh"'
    original = SETUP.read_text()
    assert marker in original
    modified = original.replace(
        marker,
        'read -rp "Unexpected final choice? [y/N]: " EXTRA\n' + marker,
    )
    script = tmp_path / "setup.sh"
    script.write_text(modified)
    script.chmod(0o755)
    shutil.copytree(ROOT / "container", tmp_path / "container")

    proc = subprocess.run(
        [
            "python3", str(DRIVER), "--setup-cmd", str(script),
            "--tenant", "hq-trailing-drift",
            "--api-port", "29080", "--session-port", "29081",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=10,
    )

    assert proc.returncode == 2
    assert "unexpected trailing prompt" in proc.stderr
    assert "Unexpected final choice? [y/N]:" in proc.stderr
