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

    # 1. Invalid boolean string '18080' at 'Use more than one account' prompt
    bad_bool_input = "\n".join(["acme", "hq", "2", "architect", "sme-2", "18080"]) + "\n"
    proc = subprocess.run(
        [str(SETUP)],
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
        [str(SETUP)],
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

    env_content = (tmp_path / "container/.env").read_text()
    assert "API_ENABLED=1" in env_content
    assert "API_PORT=19080" in env_content
    assert "SESSION_PORT=19081" in env_content

    ports_content = (tmp_path / "container/compose.ports.yaml").read_text()
    assert "0.0.0.0:19080:8080" in ports_content
    assert "0.0.0.0:19081:8081" in ports_content


def test_drive_setup_aborts_on_prompt_drift(tmp_path):
    """When setup.sh inserts an unexpected prompt, drive-setup.py fails immediately with mismatch."""
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
    assert proc.returncode != 0
    assert "timeout" in proc.stderr.lower() or "failed matching prompt" in proc.stderr.lower() or "unexpected" in proc.stderr.lower()


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
