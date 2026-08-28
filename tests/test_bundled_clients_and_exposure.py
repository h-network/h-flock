import os
import subprocess
import sys
import yaml
from pathlib import Path

ROOT = Path(__file__).parents[1]
DOCKERFILE = ROOT / "container/Dockerfile"
COMPOSE = ROOT / "container/compose.yaml"
ENTRYPOINT = ROOT / "container/entrypoint.sh"
SETUP = ROOT / "setup.sh"
FLOCK_COMPOSE = ROOT / "container/flock-compose.sh"
GITIGNORE = ROOT / ".gitignore"


def test_dockerfile_copies_clients():
    content = DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY clients/ ./clients/" in content
    assert "/app/clients" in content


def test_compose_yaml_has_no_ports_key():
    content = COMPOSE.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    assert "ports" not in parsed["services"]["tenant"], "Base compose.yaml must not carry a ports key"
    assert 'API_HOST: "${API_HOST:-}"' in content
    assert 'SESSION_HOST: "${SESSION_HOST:-}"' in content
    assert 'TELEGRAM_BOT_TOKEN: "${TELEGRAM_BOT_TOKEN:-}"' in content
    assert 'TELEGRAM_CHAT_ID: "${TELEGRAM_CHAT_ID:-}"' in content
    assert 'TELEGRAM_VOICE: "${TELEGRAM_VOICE:-0}"' in content
    assert '${FLOCK_TENANT_ENV_FILE:?' in content


def test_gitignore_contains_tenant_state():
    content = GITIGNORE.read_text(encoding="utf-8")
    assert "tenants/" in content


def test_flock_compose_helper_logic(tmp_path):
    """flock-compose.sh builds FLOCK_COMPOSE_ARGS array conditionally based on compose.ports.yaml."""
    c_dir = tmp_path / "container"
    c_dir.mkdir()
    (c_dir / "compose.yaml").write_text("services:\n  tenant:\n    image: test\n")
    tenant_dir = tmp_path / "tenants" / "hq"
    tenant_dir.mkdir(parents=True)
    
    script = f"""#!/usr/bin/env bash
set -e
export FLOCK_REPO_ROOT="{tmp_path}"
. "{FLOCK_COMPOSE}"
flock_compose_args hq
printf '%s\n' "${{FLOCK_COMPOSE_ARGS[@]}}"
printf 'env=%s\n' "$TENANT_ENV_FILE"
"""
    run_file = tmp_path / "run.sh"
    run_file.write_text(script)
    run_file.chmod(0o755)
    
    # 1. Without ports fragment
    out = subprocess.check_output([str(run_file)], text=True).splitlines()
    assert out == ["-f", f"{tmp_path}/container/compose.yaml", f"env={tenant_dir}/.env"]

    # 2. With ports fragment
    (tenant_dir / "compose.ports.yaml").write_text("services:\n  tenant:\n    ports:\n      - 8080:8080\n")
    out2 = subprocess.check_output([str(run_file)], text=True).splitlines()
    assert out2 == [
        "-f", f"{tmp_path}/container/compose.yaml",
        "-f", f"{tenant_dir}/compose.ports.yaml",
        f"env={tenant_dir}/.env",
    ]


def test_entrypoint_starts_telegram_client_when_configured():
    """When TELEGRAM_BOT_TOKEN is set and API_ENABLED is 1, entrypoint starts clients.telegram.bot."""
    script = ENTRYPOINT.read_text(encoding="utf-8")
    assert "start_client telegram" in script
    assert "TELEGRAM_BOT_TOKEN" in script
    assert 'wait "$critical_pid"' in script


def test_entrypoint_skips_telegram_client_when_api_disabled():
    script = ENTRYPOINT.read_text(encoding="utf-8")
    assert "client_skipped" in script
    assert "telegram configured but API_ENABLED is 0" in script


def test_entrypoint_start_client_does_not_abort_tenant():
    """A failing bundled client must not kill the tenant."""
    script = ENTRYPOINT.read_text(encoding="utf-8")
    assert "start_client() {" in script
    assert 'pids+=("$pid")' not in script[script.index("start_client() {"):script.index("shutdown() {")]


def test_setup_splits_api_start_and_publish_questions():
    content = SETUP.read_text(encoding="utf-8")
    assert "Start the REST API door inside the tenant? [y/N]" in content
    assert "Reach the REST API from outside the container" in content
    assert "Run the Telegram bot in this tenant? [y/N]" in content
    assert "Telegram Bot Token" in content
    assert "Telegram Chat ID" in content
    assert "Enable spoken voice replies?" in content
    assert '$TENANT_DIR/compose.ports.yaml' in content
    assert "container/flock-compose.sh" in content


def test_setup_does_not_leak_telegram_token_in_summary():
    content = SETUP.read_text(encoding="utf-8")
    summary_part = content[content.index("Tenant '${TENANT}' is healthy."):]
    assert "TELEGRAM_BOT_TOKEN" not in summary_part
