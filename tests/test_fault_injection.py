from conftest import FakeRedis, FakeRedis as RecordingRedis
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



def test_fault_wrapper_is_one_shot_and_only_matches_target_ingress():
    module = _injector_module()
    client = RecordingRedis()
    faulted = module.RefuseIngressReplyOnce(client, "target-ingress")

    assert faulted.rpush("other", b"first") == 1
    with pytest.raises(redis.ConnectionError, match="deliberate missing ingress reply"):
        faulted.rpush(b"target-ingress", b"faulted")
    assert faulted.rpush("target-ingress", b"after") == 1

    assert client.calls == [("other", (b"first",)), ("target-ingress", (b"after",))]
    assert faulted.fired is True


def test_partial_wrapper_allows_roster_removal_then_refuses_resource_purge():
    module = _partial_injector_module()


    client = FakeRedis()
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


def _is_allowed_logging_read(node: "ast.AST") -> bool:
    import ast
    if not isinstance(node, ast.Assign):
        return False
    if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name) or node.targets[0].id != "_WRITER":
        return False
    val = node.value
    if not isinstance(val, ast.Call):
        return False
    if not (isinstance(val.func, ast.Attribute) and val.func.attr == "get"):
        return False
    if not (isinstance(val.func.value, ast.Attribute) and val.func.value.attr == "environ"):
        return False
    if not (isinstance(val.func.value.value, ast.Name) and val.func.value.value.id == "os"):
        return False
    if len(val.args) != 1 or not isinstance(val.args[0], ast.Constant) or val.args[0].value != "FLOCK_WRITER":
        return False
    if val.keywords:
        return False
    return True


def test_shipping_source_has_no_writer_assignments():
    """Structural invariant: shipping source never assigns FLOCK_WRITER or sets writer: fault-injection."""
    import ast
    src_dir = ROOT / "src"
    py_files = sorted(src_dir.rglob("*.py"))
    assert len(py_files) >= 10, f"Expected at least 10 python files in src/, found {len(py_files)}"

    violations = []
    known_read_found = 0
    logging_rel_path = Path("src/flock/bus/logging.py")

    for path in py_files:
        rel_path = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(rel_path))
        except SyntaxError as e:
            violations.append(f"{rel_path}:{e.lineno}: SyntaxError: {e}")
            continue

        allowed_nodes = set()
        if rel_path == logging_rel_path:
            for node in ast.walk(tree):
                if _is_allowed_logging_read(node):
                    known_read_found += 1
                    allowed_nodes.add(id(node.value.args[0]))

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant):
                if node.value == "fault-injection":
                    violations.append(f"{rel_path}:{node.lineno}: literal 'fault-injection'")
                elif node.value == "FLOCK_WRITER":
                    if id(node) not in allowed_nodes:
                        violations.append(f"{rel_path}:{node.lineno}: occurrence of 'FLOCK_WRITER'")
            elif isinstance(node, ast.Name) and node.id == "FLOCK_WRITER":
                violations.append(f"{rel_path}:{node.lineno}: identifier FLOCK_WRITER")

    if known_read_found != 1:
        violations.append(f"Expected exactly 1 known read of FLOCK_WRITER in {logging_rel_path}, found {known_read_found}")

    assert not violations, "Illegal FLOCK_WRITER or fault-injection in shipping source:\n" + "\n".join(violations)




