import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import textwrap
import time


def _executable(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip())
    path.chmod(0o755)


def test_keep_transfers_console_ownership_without_credentials_in_argv(tmp_path):
    root = tmp_path / "repo"
    (root / "container").mkdir(parents=True)
    (root / "clients" / "web").mkdir(parents=True)
    tools = root / "tools"
    tools.mkdir()
    shutil.copy2("container/accept.sh", root / "container" / "accept.sh")
    shutil.copy2("container/drive-setup.py", root / "container" / "drive-setup.py")

    _executable(
        root / "setup.sh",
        """
        #!/usr/bin/env bash
        prompts=(
          "Pod name" "Tenant name" "How many agents?" "Agent #1 name"
          "Agent #2 name" "Use more than one account in this tenant?"
          "OAuth token for 'default'" "Default CLI (claude/codex/agy)"
          "Any agents differing from that?"
          "Point any agent at a local model provider?"
          "Start the REST API door inside the tenant?"
          "Run the Telegram bot in this tenant?"
          "Reach the REST API from outside the container"
          "Host port for the REST API"
          "Reach the session console from outside the container"
          "Host port for the session console"
          "Reach published doors from another machine"
          "Path to a TLS certificate" "Generate a self-signed certificate?"
        )
        for prompt in "${prompts[@]}"; do read -rp "$prompt: " answer; done
        touch created
        cat > container/.env <<EOF
        API_ENABLED=1
        API_PORT=18080
        API_TOKEN=token-sentinel
        EOF
        echo healthy
        """,
    )
    _executable(
        root / "container" / "plumbing-check.sh",
        """
        #!/usr/bin/env bash
        echo 'PASS=1 FAIL=0'
        """,
    )
    _executable(
        tools / "docker",
        """
        #!/usr/bin/env bash
        case "$1 $2" in
          'ps -aq') [ -f created ] && echo container-id ;;
          'inspect --format') echo healthy ;;
          'exec h-flock-keep-proof-tenant-1') echo architect ;;
        esac
        """,
    )
    _executable(
        tools / "curl",
        """
        #!/usr/bin/env bash
        printf 200
        """,
    )
    _executable(
        tools / "openssl",
        """
        #!/usr/bin/env bash
        echo secret-sentinel
        """,
    )
    (root / "clients" / "web" / "server.py").write_text(
        """import os, pathlib, time
pathlib.Path('../../console-env').write_text(
    os.environ.get('API_TOKEN', '') + '\\n' + os.environ.get('HFLOCK_SECRET', '') + '\\n'
)
pathlib.Path('../../console-pid').write_text(str(os.getpid()))
time.sleep(60)
"""
    )
    (root / "clients" / "web" / "flow-check.py").write_text("")

    env = os.environ.copy()
    env["PATH"] = f"{tools}:{env['PATH']}"
    proc = subprocess.run(
        [
            "bash",
            "container/accept.sh",
            "--tenant",
            "keep-proof",
            "--api-port",
            "18080",
            "--session-port",
            "18081",
            "--console-port",
            "18099",
            "--keep",
        ],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )

    for _ in range(100):
        if (root / "console-pid").exists():
            break
        time.sleep(0.01)
    console_pid = int((root / "console-pid").read_text())
    try:
        match = re.search(
            r"kept: container=h-flock-keep-proof-tenant-1; console_pid=(\d+) "
            r"\(stop console: kill \1\)",
            proc.stdout,
        )
        assert match, proc.stdout + proc.stderr
        assert int(match.group(1)) == console_pid
        for _ in range(100):
            if (root / "console-env").exists():
                break
            time.sleep(0.01)
        assert (root / "console-env").read_text().splitlines() == [
            "token-sentinel",
            "secret-sentinel",
        ]
        cmdline = Path(f"/proc/{console_pid}/cmdline").read_bytes().split(b"\0")
        assert b"token-sentinel" not in cmdline
        assert b"secret-sentinel" not in cmdline
        assert b"--token" not in cmdline
        assert b"--secret" not in cmdline
    finally:
        os.kill(console_pid, signal.SIGTERM)
