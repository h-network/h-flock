import importlib.util
import subprocess
from pathlib import Path

import pytest
import redis


ROOT = Path(__file__).parents[1]
INJECTOR = ROOT / "container" / "scenarios" / "inject-forward-unknown.py"
HARNESS = ROOT / "container" / "scenarios" / "fault-forward-unknown.sh"


def _injector_module():
    spec = importlib.util.spec_from_file_location("inject_forward_unknown", INJECTOR)
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
