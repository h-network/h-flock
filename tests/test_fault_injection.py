import importlib.util
import subprocess
from pathlib import Path

import pytest
import redis


ROOT = Path(__file__).parents[1]
INJECTOR = ROOT / "container" / "scenarios" / "inject-forward-unknown.py"
HARNESS = ROOT / "container" / "scenarios" / "fault-forward-unknown.sh"
PARTIAL_INJECTOR = ROOT / "container" / "scenarios" / "inject-partial-control.py"
PARTIAL_HARNESS = ROOT / "container" / "scenarios" / "partial-control-damage.sh"


def _injector_module():
    spec = importlib.util.spec_from_file_location("inject_forward_unknown", INJECTOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _partial_injector_module():
    spec = importlib.util.spec_from_file_location("inject_partial_control", PARTIAL_INJECTOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RecordingRedis:
    def __init__(self):
        self.calls = []

    def rpush(self, key, *values):
        self.calls.append((key, values))
        return len(self.calls)


def test_fault_wrapper_is_one_shot_and_only_matches_target_ingress():
    module = _injector_module()
    client = RecordingRedis()
    faulted = module.RefuseIngressReplyOnce(client, "target-ingress")

    assert faulted.rpush("other", b"first") == 1
    with pytest.raises(redis.ConnectionError, match="deliberate missing ingress reply"):
        faulted.rpush(b"target-ingress", b"faulted")
    assert faulted.rpush("target-ingress", b"after") == 2

    assert client.calls == [("other", (b"first",)), ("target-ingress", (b"after",))]
    assert faulted.fired is True


def test_partial_wrapper_allows_roster_removal_then_refuses_resource_purge():
    module = _partial_injector_module()

    class Client:
        def __init__(self):
            self.calls = []

        def hdel(self, key, *fields):
            self.calls.append(("hdel", key, fields))
            return 1

        def delete(self, *keys):
            self.calls.append(("delete", keys))
            return 1

    client = Client()
    faulted = module.RefusePurgeReplyOnce(client, {"state-key"})
    assert faulted.hdel("pod:tenant:roster", "sme-2") == 1
    with pytest.raises(redis.ConnectionError, match="deliberate resource purge reply loss"):
        faulted.delete("state-key")
    assert faulted.fired is True
    assert faulted.roster_removed is True


@pytest.mark.parametrize("arguments", [[], ["yes"], ["I_UNDERSTAND_THIS_INJECTS_AND_DESTROYS_A_TENANT", "extra"]])
def test_partial_harness_refuses_without_exact_destructive_phrase(arguments):
    result = subprocess.run(
        ["bash", str(PARTIAL_HARNESS), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == (
        "REFUSED: pass I_UNDERSTAND_THIS_INJECTS_AND_DESTROYS_A_TENANT exactly\n"
    )


@pytest.mark.parametrize("arguments", [[], ["yes"], ["I_UNDERSTAND_THIS_INJECTS_AND_DESTROYS_A_TENANT", "extra"]])
def test_fault_harness_refuses_without_exact_destructive_phrase(arguments):
    result = subprocess.run(
        ["bash", str(HARNESS), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == (
        "REFUSED: pass I_UNDERSTAND_THIS_INJECTS_AND_DESTROYS_A_TENANT exactly\n"
    )


def test_shipping_source_has_no_writer_assignments():
    """Structural invariant: shipping source never assigns FLOCK_WRITER or sets writer: fault-injection."""
    src_dir = ROOT / "src"
    violations = []
    allowed_logging_line = '_WRITER = os.environ.get("FLOCK_WRITER")'

    for path in sorted(src_dir.rglob("*.py")):
        rel_path = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        for line_num, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if "FLOCK_WRITER" in stripped:
                if rel_path == Path("src/flock/bus/logging.py") and stripped == allowed_logging_line:
                    continue
                violations.append(f"{rel_path}:{line_num}:{stripped}")
            elif "fault-injection" in stripped:
                violations.append(f"{rel_path}:{line_num}:{stripped}")

    assert not violations, "Illegal FLOCK_WRITER or fault-injection in shipping source:\n" + "\n".join(violations)


