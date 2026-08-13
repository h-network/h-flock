#!/usr/bin/env python3
"""Deterministic, idempotent vocabulary rename codemod for h-flock.

Executes the five vocabulary decisions from BUILD-49-vocabulary.md / GLOSSARY.md:
  1. router (L2 component) -> switch (Tier A prose, Tier B code/modules)
  2. adapter (both directions) -> egress_adapter / ingress_adapter (Tier B code)
  3. vab (roster value) -> port_type (Tier C Redis/keys/functions)
  4. endpoint (model service) -> provider (Tier C Redis/env vars)
  5. producer / recipient -> source / destination (Tier D wire / envelope v2)

Usage:
  python3 tools/rename_vocabulary.py --tier A
  python3 tools/rename_vocabulary.py --tier B
  python3 tools/rename_vocabulary.py --tier C
  python3 tools/rename_vocabulary.py --tier D
  python3 tools/rename_vocabulary.py --tier all
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def check_dirty_tree(force: bool = False) -> None:
    if force:
        return
    res = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=REPO_ROOT)
    if res.stdout.strip():
        sys.stderr.write("Error: Working tree is dirty. Commit or stash changes before running codemod (or pass --force).\n")
        sys.exit(1)


def replace_in_file(file_path: Path, patterns: list[tuple[str | re.Pattern, str]]) -> int:
    if not file_path.exists() or file_path.is_symlink():
        return 0
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 0

    new_content = content
    changes = 0
    for pat, repl in patterns:
        if isinstance(pat, str):
            count = new_content.count(pat)
            if count > 0:
                new_content = new_content.replace(pat, repl)
                changes += count
        else:
            new_content, count = pat.subn(repl, new_content)
            changes += count

    if new_content != content:
        file_path.write_text(new_content, encoding="utf-8")
    return changes


def get_target_files(directories: list[Path], extensions: set[str]) -> list[Path]:
    files = []
    for d in directories:
        if d.is_file():
            if d.suffix in extensions or d.name in {"pyproject.toml", "setup.sh", "README.md"}:
                files.append(d)
        elif d.is_dir():
            for ext in extensions:
                files.extend(d.rglob(f"*{ext}"))
            for name in ["setup.sh", "pyproject.toml"]:
                f = d / name
                if f.exists():
                    files.append(f)
    return sorted(list(set(files)))


def run_tier_a() -> dict[str, int]:
    """Tier A — Prose (router -> switch, adapter -> port in docs)."""
    counts = {"prose_router_to_switch": 0, "prose_adapter_to_port": 0, "file_renames": 0}

    # Rename doc file LLD-bus-and-router.md -> LLD-bus-and-switch.md
    old_doc = REPO_ROOT / "docs" / "LLD-bus-and-router.md"
    new_doc = REPO_ROOT / "docs" / "LLD-bus-and-switch.md"
    if old_doc.exists():
        if new_doc.exists():
            new_doc.unlink()
        old_doc.rename(new_doc)
        counts["file_renames"] += 1

    old_adapter_doc = REPO_ROOT / "docs" / "LLD-adapter-tmux.md"
    new_port_doc = REPO_ROOT / "docs" / "LLD-port-tmux.md"
    if old_adapter_doc.exists():
        if new_port_doc.exists():
            new_port_doc.unlink()
        old_adapter_doc.rename(new_port_doc)
        counts["file_renames"] += 1

    doc_files = list((REPO_ROOT / "docs").rglob("*.md")) + [REPO_ROOT / "README.md"]
    patterns = [
        ("LLD-bus-and-router.md", "LLD-bus-and-switch.md"),
        ("LLD-bus-and-router", "LLD-bus-and-switch"),
        ("LLD-adapter-tmux.md", "LLD-port-tmux.md"),
        ("LLD-adapter-tmux", "LLD-port-tmux"),
        (re.compile(r"\bflock\.router\b"), "flock.switch"),
        (re.compile(r"\bflock/router\b"), "flock/switch"),
        (re.compile(r"\bflock\.adapter\b"), "flock.port"),
        (re.compile(r"\bflock/adapter\b"), "flock/port"),
        (re.compile(r"\bthe router\b"), "the switch"),
        (re.compile(r"\bThe router\b"), "The switch"),
        (re.compile(r"\brouter's\b"), "switch's"),
        (re.compile(r"\bRouter's\b"), "Switch's"),
        (re.compile(r"\bthe adapter\b"), "the port"),
        (re.compile(r"\bThe adapter\b"), "The port"),
        (re.compile(r"\badapter's\b"), "port's"),
        (re.compile(r"\bAdapter's\b"), "Port's"),
        (re.compile(r"\bROUTER\b"), "SWITCH"),
        (re.compile(r"\bRouter\b"), "Switch"),
        (re.compile(r"\brouter\b"), "switch"),
        (re.compile(r"\bADAPTER\b"), "PORT"),
        (re.compile(r"\bAdapter\b"), "Port"),
        (re.compile(r"\badapter\b"), "port"),
    ]

    for fpath in doc_files:
        counts["prose_router_to_switch"] += replace_in_file(fpath, patterns)

    return counts


def run_tier_b() -> dict[str, int]:
    """Tier B — Identifiers & Code Modules (router -> switch, adapter -> port/send/deliver)."""
    counts = {"code_router_to_switch": 0, "adapter_renames": 0, "file_moves": 0}

    # 1. Directory & File moves
    old_router_dir = REPO_ROOT / "src" / "flock" / "router"
    new_switch_dir = REPO_ROOT / "src" / "flock" / "switch"
    if old_router_dir.exists():
        if new_switch_dir.exists():
            shutil.rmtree(new_switch_dir)
        old_router_dir.rename(new_switch_dir)
        counts["file_moves"] += 1

    old_adapter_dir = REPO_ROOT / "src" / "flock" / "adapter"
    new_port_dir = REPO_ROOT / "src" / "flock" / "port"
    if old_adapter_dir.exists():
        if new_port_dir.exists():
            shutil.rmtree(new_port_dir)
        old_adapter_dir.rename(new_port_dir)
        counts["file_moves"] += 1

    old_cli_send = REPO_ROOT / "src" / "flock" / "port" / "cli.py"
    new_send_py = REPO_ROOT / "src" / "flock" / "port" / "send.py"
    if old_cli_send.exists():
        if new_send_py.exists():
            new_send_py.unlink()
        old_cli_send.rename(new_send_py)
        counts["file_moves"] += 1
        counts["adapter_renames"] += 1

    old_runner_deliver = REPO_ROOT / "src" / "flock" / "port" / "runner.py"
    new_deliver_py = REPO_ROOT / "src" / "flock" / "port" / "deliver.py"
    if old_runner_deliver.exists():
        if new_deliver_py.exists():
            new_deliver_py.unlink()
        old_runner_deliver.rename(new_deliver_py)
        counts["file_moves"] += 1
        counts["adapter_renames"] += 1

    old_test_router = REPO_ROOT / "tests" / "test_router.py"
    new_test_switch = REPO_ROOT / "tests" / "test_switch.py"
    if old_test_router.exists():
        if new_test_switch.exists():
            new_test_switch.unlink()
        old_test_router.rename(new_test_switch)
        counts["file_moves"] += 1

    old_test_adapter = REPO_ROOT / "tests" / "test_adapter.py"
    new_test_port = REPO_ROOT / "tests" / "test_port.py"
    if old_test_adapter.exists():
        if new_test_port.exists():
            new_test_port.unlink()
        old_test_adapter.rename(new_test_port)
        counts["file_moves"] += 1

    # 2. Code replacements across src/, tests/, container/, pyproject.toml
    target_files = get_target_files(
        [REPO_ROOT / "src", REPO_ROOT / "tests", REPO_ROOT / "container", REPO_ROOT / "pyproject.toml"],
        {".py", ".sh", ".yaml", ".toml"},
    )

    router_patterns = [
        ("from flock.router", "from flock.switch"),
        ("import flock.router", "import flock.switch"),
        ("flock.router", "flock.switch"),
        ("flock/router", "flock/switch"),
        ('"module": "router"', '"module": "switch"'),
        ("'module': 'router'", "'module': 'switch'"),
        ('emit("router"', 'emit("switch"'),
        ("emit('router'", "emit('switch'"),
        ('log_record("router"', 'log_record("switch"'),
        ("log_record('router'", "log_record('switch'"),
        (re.compile(r"\bclass Router\b"), "class Switch"),
        (re.compile(r"\bRouter\("), "Switch("),
        (re.compile(r"\bRouter\b"), "Switch"),
        (re.compile(r"\brouter_pass\b"), "switch_pass"),
        (re.compile(r"\brouter_service\b"), "switch_service"),
        (re.compile(r"\brouter_verdict\b"), "switch_verdict"),
        (re.compile(r"\brouter_maintenance_pass\b"), "switch_maintenance_pass"),
        (re.compile(r"\btest_router_"), "test_switch_"),
        (re.compile(r"\brouter\b"), "switch"),
    ]

    adapter_patterns = [
        ("from .runner import run_adapter", "from .deliver import run_port"),
        ("from flock.adapter.cli", "from flock.port.send"),
        ("from flock.adapter.runner", "from flock.port.deliver"),
        ("from flock.adapter.openers", "from flock.port.openers"),
        ("from flock.adapter import runner", "from flock.port import deliver"),
        ("from flock.adapter import cli", "from flock.port import send"),
        ("from flock.adapter import openers", "from flock.port import openers"),
        ("from flock.adapter import", "from flock.port import"),
        ("import flock.adapter.runner", "import flock.port.deliver"),
        ("import flock.adapter.cli", "import flock.port.send"),
        ("import flock.adapter.openers", "import flock.port.openers"),
        ("import flock.adapter", "import flock.port"),
        ("flock.adapter.runner", "flock.port.deliver"),
        ("flock.adapter.cli", "flock.port.send"),
        ("flock.adapter.openers", "flock.port.openers"),
        ("flock.adapter", "flock.port"),
        ("flock/adapter", "flock/port"),
        ("run_adapter", "run_port"),
        ("hasattr(runner,", "hasattr(deliver,"),
        ("Path(runner.__file__)", "Path(deliver.__file__)"),
        ("test_adapter", "test_port"),
        ("test_run_adapter", "test_run_port"),
    ]

    for fpath in target_files:
        counts["code_router_to_switch"] += replace_in_file(fpath, router_patterns)
        counts["adapter_renames"] += replace_in_file(fpath, adapter_patterns)

    return counts


def run_tier_c() -> dict[str, int]:
    """Tier C — Redis keys & Env Vars (vab -> port_type, endpoint -> provider)."""
    counts = {"vab_to_port_type": 0, "endpoint_to_provider": 0}

    # Rename test_local_endpoint.py -> test_local_provider.py
    old_test_endpoint = REPO_ROOT / "tests" / "test_local_endpoint.py"
    new_test_provider = REPO_ROOT / "tests" / "test_local_provider.py"
    if old_test_endpoint.exists():
        if new_test_provider.exists():
            new_test_provider.unlink()
        old_test_endpoint.rename(new_test_provider)

    target_files = get_target_files(
        [REPO_ROOT / "src", REPO_ROOT / "tests", REPO_ROOT / "container", REPO_ROOT / "docs", REPO_ROOT / "clients", REPO_ROOT / "setup.sh"],
        {".py", ".sh", ".yaml", ".md", ".js", ".html", ".css"},
    )

    # Special handling for resource literals in src/flock/bus/resources.py
    resources_py = REPO_ROOT / "src" / "flock" / "bus" / "resources.py"
    if resources_py.exists():
        replace_in_file(resources_py, [('"endpoint"', '"provider"'), ("'endpoint'", "'provider'")])

    # 1. vab -> port_type
    vab_patterns = [
        ("from flock.bus.roster import vab", "from flock.bus.roster import port_type"),
        ("from flock.bus import vab", "from flock.bus import port_type"),
        ("import vab", "import port_type"),
        ("def vab(", "def port_type("),
        ("agent_vab", "agent_port_type"),
        ("existing_vab", "existing_port_type"),
        ("raw_vab", "raw_port_type"),
        ("vab_name", "port_type_name"),
        ("vab_map", "port_type_map"),
        ("roster_vab", "roster_port_type"),
        ("custom_vab", "custom_port_type"),
        ("vab_api", "port_type_api"),
        ("vab(", "port_type("),
        ('"vab":', '"port_type":'),
        ("'vab':", "'port_type':"),
        ('body["vab"]', 'body["port_type"]'),
        ("body['vab']", "body['port_type']"),
        ('payload.get("vab"', 'payload.get("port_type"'),
        ("payload.get('vab'", "payload.get('port_type'"),
        ('payload["vab"]', 'payload["port_type"]'),
        ("payload['vab']", "payload['port_type']"),
        ("StartAgent payload.vab", "StartAgent payload.port_type"),
        ("unroutable VAB", "unroutable port_type"),
        ("unroutable_vab", "unroutable_port_type"),
        ("non_tmux_vab", "non_tmux_port_type"),
        ("test_tmuxhost_filters_non_tmux_vab", "test_tmuxhost_filters_non_tmux_port_type"),
        ("test_run_adapter_vab_api_pops_and_writes_mailbox", "test_run_adapter_port_type_api_pops_and_writes_mailbox"),
        ("test_run_adapter_unroutable_vab_pops_and_dead_letters", "test_run_adapter_unroutable_port_type_pops_and_dead_letters"),
        (re.compile(r"\bvab\b"), "port_type"),
        (re.compile(r"\bVAB\b"), "port_type"),
    ]

    # 2. endpoint -> provider
    endpoint_patterns = [
        ("AGENT_ENDPOINTS", "AGENT_PROVIDERS"),
        ("ENDPOINT_", "PROVIDER_"),
        ('resource="endpoint"', 'resource="provider"'),
        ("resource='endpoint'", "resource='provider'"),
        ('agent:<name>:endpoint', 'agent:<name>:provider'),
        ('":agent:{agent}:endpoint"', '":agent:{agent}:provider"'),
        ('endpoint_key', 'provider_key'),
        ('endpoint_map', 'provider_map'),
        ('old_endpoint', 'old_provider'),
        ('first_endpoint', 'first_provider'),
        ('get_agent_endpoint', 'get_agent_provider'),
        ('USE_ENDPOINT', 'USE_PROVIDER'),
        ('ENDPOINT_MAP', 'PROVIDER_MAP'),
        ('EP_UPPER', 'PR_UPPER'),
        ('test_tmuxhost_initial_session_resolves_agent_endpoint', 'test_tmuxhost_initial_session_resolves_agent_provider'),
        ('test_endpoint_agent_needs_no_vendor_credential_and_clears_stale_status', 'test_provider_agent_needs_no_vendor_credential_and_clears_stale_status'),
        ('test_no_endpoint_means_the_vendor_and_no_anthropic_vars', 'test_no_provider_means_the_vendor_and_no_anthropic_vars'),
        ('test_endpoint_strips_v1_and_sets_all_three_tiers', 'test_provider_strips_v1_and_sets_all_three_tiers'),
        ('test_endpoint_and_profile_coexist', 'test_provider_and_profile_coexist'),
        ('test_fresh_hire_with_profile_and_endpoint_leaves_creation_to_tmuxhost', 'test_fresh_hire_with_profile_and_provider_leaves_creation_to_tmuxhost'),
        ('payload.get("endpoint")', 'payload.get("provider")'),
        ('payload.get(\'endpoint\')', 'payload.get(\'provider\')'),
        ('StartAgent payload.endpoint', 'StartAgent payload.provider'),
        ('endpoint=endpoint', 'provider=provider'),
        ('endpoint: dict | None', 'provider: dict | None'),
        (re.compile(r"\bendpoint\b"), "provider"),
        (re.compile(r"\bendpoints\b"), "providers"),
        # Restore FastAPI route.endpoint property access
        ("route.provider", "route.endpoint"),
        ("post_route.provider", "post_route.endpoint"),
        ("alerts_route.provider", "alerts_route.endpoint"),
        ("all_boards_route.provider", "all_boards_route.endpoint"),
    ]

    for fpath in target_files:
        counts["vab_to_port_type"] += replace_in_file(fpath, vab_patterns)
        counts["endpoint_to_provider"] += replace_in_file(fpath, endpoint_patterns)

    return counts


def run_tier_d() -> dict[str, int]:
    """Tier D — Wire surface (producer/recipient -> source/destination, custody module -> port). Envelope v2."""
    counts = {"producer_to_source": 0, "recipient_to_destination": 0, "custody_module_adapter_to_port": 0}

    target_files = get_target_files(
        [REPO_ROOT / "src", REPO_ROOT / "tests", REPO_ROOT / "clients", REPO_ROOT / "docs", REPO_ROOT / "container"],
        {".py", ".md", ".html", ".js", ".sh"},
    )

    producer_patterns = [
        ('"producer"', '"source"'),
        ("'producer'", "'source'"),
        ('producer=', 'source='),
        ('producer:', 'source:'),
        ('producer,', 'source,'),
        ('producer_stamped', 'source_stamped'),
        ('forged producer', 'forged source'),
        ('[message from {producer}]', '[message from {source}]'),
        ('[message from <producer>]', '[message from <source>]'),
        ('producer is', 'source is'),
        ('\"producer\":', '\"source\":'),
        (re.compile(r"\bproducer\b"), "source"),
    ]

    recipient_patterns = [
        ('"recipient"', '"destination"'),
        ("'recipient'", "'destination'"),
        ('recipient=', 'destination='),
        ('recipient:', 'destination:'),
        ('recipient,', 'destination,'),
        ('\"recipient\":', '\"destination\":'),
        (re.compile(r"\brecipient\b"), "destination"),
    ]

    custody_module_patterns = [
        ('["adapter", "router", "router", "adapter", "adapter"]', '["port", "switch", "switch", "port", "port"]'),
        ('["adapter", "switch", "switch", "adapter", "adapter"]', '["port", "switch", "switch", "port", "port"]'),
        ('"module": "adapter"', '"module": "port"'),
        ("'module': 'adapter'", "'module': 'port"'),
        ('"module":"adapter"', '"module":"port"'),
        ("'module':'adapter'", "'module':'port'"),
        ('module="adapter"', 'module="port"'),
        ("module='adapter'", "module='port'"),
        ('module: str = "adapter"', 'module: str = "port"'),
        ("module: str = 'adapter'", "module: str = 'port'"),
        ('emit("adapter"', 'emit("port"'),
        ("emit('adapter'", "emit('port'"),
        ('log_record("adapter"', 'log_record("port"'),
        ("log_record('adapter'", "log_record('port'"),
        ('{"module": "adapter"', '{"module": "port"'),
        ('{"module":"adapter"', '{"module":"port"'),
        (re.compile(r'"adapter"'), '"port"'),
        (re.compile(r"'adapter'"), "'port'"),
    ]

    for fpath in target_files:
        counts["producer_to_source"] += replace_in_file(fpath, producer_patterns)
        counts["recipient_to_destination"] += replace_in_file(fpath, recipient_patterns)
        counts["custody_module_adapter_to_port"] += replace_in_file(fpath, custody_module_patterns)

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute h-flock vocabulary rename codemod.")
    parser.add_argument("--tier", choices=["A", "B", "C", "D", "all"], required=True, help="Rename tier to execute")
    parser.add_argument("--force", action="store_true", help="Force execution even if git working tree is dirty")
    args = parser.parse_args()

    check_dirty_tree(args.force)

    print(f"=== Running Vocabulary Rename Codemod — Tier {args.tier} ===")

    summary = {}
    if args.tier in ("A", "all"):
        res = run_tier_a()
        summary.update(res)
        print(f"Tier A complete: {res}")
    if args.tier in ("B", "all"):
        res = run_tier_b()
        summary.update(res)
        print(f"Tier B complete: {res}")
    if args.tier in ("C", "all"):
        res = run_tier_c()
        summary.update(res)
        print(f"Tier C complete: {res}")
    if args.tier in ("D", "all"):
        res = run_tier_d()
        summary.update(res)
        print(f"Tier D complete: {res}")

    print("\n=== Codemod Execution Summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
