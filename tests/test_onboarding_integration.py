import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import shutil
import subprocess
import threading

import pytest


ROOT = Path(__file__).parents[1]
TOOL = ROOT / "container/scenarios/tmux-onboarding-integration.sh"
JUDGE = ROOT / "container/scenarios/onboarding-custody.py"


@pytest.fixture
def provider_url():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"data": [{"id": "served-model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


def run_tool(output, *, env=None, tool=TOOL):
    clean = {key: value for key, value in os.environ.items() if key not in {"TENANT", "AGENT_CLIS"}}
    clean.update(env or {})
    return subprocess.run(
        ["/bin/bash", str(tool), str(output)],
        cwd=ROOT,
        env=clean,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_manual_tool_is_outside_acceptance_and_never_emits_result():
    text = TOOL.read_text()
    assert "MANUAL INTEGRATION TOOL" in text
    assert 'echo "RESULT ' not in text
    assert "tmux-onboarding-integration" not in (ROOT / "container/accept.sh").read_text()


def test_usage_documents_provider_convention_and_keep_default():
    text = TOOL.read_text()
    assert "PROVIDER_LOCAL_URL=http://HOST:PORT" in text
    assert "PROVIDER_LOCAL_MODEL=MODEL" in text
    assert "PROVIDER_<NAME>_*" in text
    assert "KEEP=1 leaves the owned tenant running (default)" in text


def test_log_pane_disagreement_is_a_category_not_a_fake_failure_count():
    text = TOOL.read_text()
    body = re.search(r"onboarding_log_disagreement\(\) \{\n(.*?)\n\}", text, re.DOTALL).group(1)
    assert 'ONBOARDING fail reason=log_disagrees_with_pane smes=$1' in body
    assert "exit 6" in body
    assert "failed=" not in body
    assert "onboarding_log_disagreement \"$disagreement_smes\"" in text
    assert "onboarding_fail 6 log_disagrees_with_pane" not in text


def test_custody_summary_scopes_by_time_source_stream_and_destination(tmp_path):
    rows = [
        {"event": "opened", "stream_id": "stale", "source": "architect", "destination": "sme-1"},
        {"event": "sent", "stream_id": "one", "source": "architect", "destination": "sme-1"},
        {"event": "opened", "stream_id": "one", "source": "architect", "destination": "sme-1"},
        {"event": "sent", "stream_id": "two", "source": "architect", "destination": "sme-2"},
        {"event": "dead_lettered", "stream_id": "two", "source": "architect", "destination": "sme-2"},
        {"event": "opened", "stream_id": "other", "source": "someone-else", "destination": "sme-2"},
    ]
    log = tmp_path / "custody.log"
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    result = subprocess.run(
        ["python3", str(JUDGE), str(log), "--after-line", "1", "--source", "architect",
         "--destination", "sme-1", "--destination", "sme-2",
         "--marked-destination", "sme-1"],
        capture_output=True, text=True, check=True,
    )
    summary = json.loads(result.stdout)
    assert summary["stream_ids"] == ["one", "two"]
    assert summary["dead_stream_ids"] == ["two"]
    assert summary["destinations"]["sme-1"] == {
        "stream_ids": ["one"], "opened_stream_ids": ["one"],
        "dead_lettered_stream_ids": [], "sent": 1, "opened": 1, "dead_lettered": 0,
    }
    assert summary["destinations"]["sme-2"]["dead_lettered"] == 1
    assert summary["observed_destinations"] == ["sme-1"]
    assert summary["pane_disagreements"] == []


def test_custody_summary_never_treats_an_orphan_terminal_record_as_delivery(tmp_path):
    log = tmp_path / "custody.log"
    log.write_text(json.dumps({
        "event": "opened", "stream_id": "missing-sent",
        "source": "architect", "destination": "sme-1",
    }) + "\n")
    result = subprocess.run(
        ["python3", str(JUDGE), str(log), "--source", "architect", "--destination", "sme-1"],
        capture_output=True, text=True, check=True,
    )
    summary = json.loads(result.stdout)
    assert summary["terminal_without_sent"] == ["missing-sent"]
    assert summary["destinations"]["sme-1"]["opened"] == 0


def test_opened_without_pane_marker_is_a_named_log_disagreement(tmp_path):
    log = tmp_path / "custody.log"
    log.write_text("\n".join(json.dumps({
        "event": event, "stream_id": "delivered", "source": "architect", "destination": "sme-1",
    }) for event in ("sent", "opened")) + "\n")
    result = subprocess.run(
        ["python3", str(JUDGE), str(log), "--source", "architect", "--destination", "sme-1"],
        capture_output=True, text=True, check=True,
    )
    summary = json.loads(result.stdout)
    assert summary["observed_destinations"] == []
    assert summary["pane_disagreements"] == ["sme-1"]


def test_observed_destinations_stay_sticky_after_markers_scroll_away(tmp_path):
    log = tmp_path / "custody.log"
    rows = []
    for destination in ("sme-1", "sme-2"):
        rows.extend({
            "event": event, "stream_id": destination, "source": "architect",
            "destination": destination,
        } for event in ("sent", "opened"))
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    result = subprocess.run(
        ["python3", str(JUDGE), str(log), "--source", "architect",
         "--destination", "sme-1", "--destination", "sme-2",
         "--previously-observed", "sme-1", "--marked-destination", "sme-2"],
        capture_output=True, text=True, check=True,
    )
    summary = json.loads(result.stdout)
    assert summary["observed_destinations"] == ["sme-1", "sme-2"]
    assert summary["pane_disagreements"] == []


def test_custody_summary_counts_unreadable_json_in_the_run(tmp_path):
    log = tmp_path / "custody.log"
    log.write_text('{"event":"sent"\n')
    result = subprocess.run(
        ["python3", str(JUDGE), str(log), "--source", "architect", "--destination", "sme-1"],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout)["parse_failures"] == 1


def test_missing_tenant_is_incomplete_with_actionable_reason(tmp_path):
    result = run_tool(tmp_path / "evidence")
    assert result.returncode == 100
    assert "ONBOARDING incomplete reason=tenant_required" in result.stderr


def test_wrong_cli_refuses_before_docker_and_provider_token_is_captured_redacted(tmp_path, provider_url):
    token = "live-provider-token-sentinel"
    result = run_tool(
        tmp_path / "evidence",
        env={
            "TENANT": "wrong-cli", "AGENT_CLIS": "sme-1=codex",
            "PROVIDER_LOCAL_URL": provider_url, "PROVIDER_LOCAL_MODEL": "served-model",
            "PROVIDER_LOCAL_TOKEN": token, "PATH": "/usr/bin:/bin",
        },
    )
    assert result.returncode == 100
    assert "ONBOARDING incomplete reason=wrong_cli" in result.stderr
    evidence = (tmp_path / "evidence/provider.json").read_text()
    assert token not in evidence
    assert json.loads(evidence)["token"] == "<redacted>"


def test_existing_tenant_is_never_adopted_or_torn_down(tmp_path, provider_url):
    tools = tmp_path / "tools"
    tools.mkdir()
    calls = tmp_path / "docker.calls"
    docker = tools / "docker"
    docker.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >>\"$DOCKER_CALLS\"\ncase \"$1 $2\" in 'ps -aq') echo existing;; esac\n")
    docker.chmod(0o755)
    result = run_tool(
        tmp_path / "evidence",
        env={
            "TENANT": "already-owned", "PROVIDER_LOCAL_URL": provider_url,
            "PROVIDER_LOCAL_MODEL": "served-model", "DOCKER_CALLS": str(calls),
            "PATH": f"{tools}:{os.environ['PATH']}",
        },
    )
    assert result.returncode == 100
    assert "ONBOARDING incomplete reason=tenant_exists" in result.stderr
    assert " down " not in calls.read_text()
    assert "TEARDOWN unavailable reason=tenant_not_owned" in result.stdout


def test_unknown_model_is_distinct_from_unreachable_endpoint(tmp_path, provider_url):
    result = run_tool(
        tmp_path / "evidence",
        env={"TENANT": "model-miss", "PROVIDER_LOCAL_URL": provider_url,
             "PROVIDER_LOCAL_MODEL": "not-served"},
    )
    assert result.returncode == 100
    assert "ONBOARDING incomplete reason=provider_model_not_served" in result.stderr


def test_keep_zero_captures_evidence_before_owned_project_teardown(tmp_path, provider_url):
    repo = tmp_path / "repo"
    (repo / "container/scenarios").mkdir(parents=True)
    shutil.copy2(TOOL, repo / "container/scenarios/tmux-onboarding-integration.sh")
    shutil.copy2(JUDGE, repo / "container/scenarios/onboarding-custody.py")
    shutil.copy2(ROOT / "container/compose.yaml", repo / "container/compose.yaml")
    shutil.copy2(ROOT / "container/flock-image.sh", repo / "container/flock-image.sh")
    tools = tmp_path / "tools"
    tools.mkdir()
    calls = tmp_path / "docker.calls"
    evidence = tmp_path / "evidence"
    docker = tools / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = compose ]; then\n"
        "  case \" $* \" in *' up -d '*) exit 1;; *' down -v '*) "
        "[ -f \"$EVIDENCE/roster.txt\" ] && seen=yes || seen=no; "
        "printf 'down evidence=%s\\n' \"$seen\" >>\"$DOCKER_CALLS\"; exit 0;; esac\n"
        "fi\nexit 0\n"
    )
    docker.chmod(0o755)
    result = run_tool(
        evidence,
        tool=repo / "container/scenarios/tmux-onboarding-integration.sh",
        env={
            "TENANT": "owned-failure", "KEEP": "0", "PROVIDER_LOCAL_URL": provider_url,
            "PROVIDER_LOCAL_MODEL": "served-model", "DOCKER_CALLS": str(calls),
            "EVIDENCE": str(evidence), "PATH": f"{tools}:{os.environ['PATH']}",
        },
    )
    assert result.returncode == 1
    assert "ONBOARDING fail failed=1 reason=tenant_start_failed" in result.stderr
    assert "down evidence=yes" in calls.read_text()
    assert "TEARDOWN command=" in result.stdout and "down -v" in result.stdout
