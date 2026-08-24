# BUILD 116 results — remove hardcoded API token from scenarios

## Result

1. **Removed Hardcoded Token from Three Scenarios (`container/scenarios/`):**
   - Replaced hardcoded token string `7af3ad5eb2cac57e9ca97a953908ef09` in:
     - `container/scenarios/api-auth-and-limits.sh:6`
     - `container/scenarios/api-concurrency-and-time.sh:6`
     - `container/scenarios/api-session-and-log-privacy.sh:6`
   - Applied in-tree standard pattern matching `container/scenarios/tmux-window-loss.sh`:
     - Reads `TOKEN` from `${API_TOKEN:-$(docker exec "$C" printenv API_TOKEN 2>/dev/null || true)}`.
     - Fails loudly with exit code 1 if `TOKEN` is empty (`if [ -z "${TOKEN:-}" ]; then echo "Error: API_TOKEN is empty. Set API_TOKEN or ensure container '$C' is running." >&2; exit 1; fi`).
     - Added `set -uo pipefail` to all three scripts.

2. **Structural Secret Scan (`container/`):**
   - Executed `git grep -nE '[a-f0-9]{32}' -- container/`.
   - Findings:
     - `container/Dockerfile:22`: `FROM ghcr.io/h-network/base@sha256:10406097c8954af16c62cf0088dea147065146bf4f667c361da96384ed02cbdc` (base image digest sha256).
     - The 3 retired scenario token lines (now removed).
     - No other 32-character hex secret candidates exist in `container/`.

3. **Persistent Regression Test Suite (`tests/test_scenario_tokens.py`):**
   - `test_api_scenarios_syntax_valid`: verifies `bash -n` on all 3 scenarios.
   - `test_api_scenarios_fail_loudly_when_token_empty`: verifies that running each scenario without `API_TOKEN` and without container exits 1 with standard error.
   - `test_no_hardcoded_token_in_scenarios`: structural assertion ensuring `7af3ad5eb2cac57e9ca97a953908ef09` is absent across `container/scenarios/*.sh`.

## Negative Controls (Falsifiability)

- **Control 1 (Re-introducing hardcoded token constant):**
  - *Mutation:* Re-added `TOKEN="${API_TOKEN:-7af3ad5eb2cac57e9ca97a953908ef09}"` to `container/scenarios/api-auth-and-limits.sh`.
  - *Observed locus:* `tests/test_scenario_tokens.py::test_no_hardcoded_token_in_scenarios` FAILED with `AssertionError: Hardcoded token found in ...`; exit 1.
- **Control 2 (Removing empty token fail-loud guard):**
  - *Mutation:* Removed empty token check from `container/scenarios/api-auth-and-limits.sh`.
  - *Observed locus:* `tests/test_scenario_tokens.py::test_api_scenarios_fail_loudly_when_token_empty` FAILED with `AssertionError: Expected api-auth-and-limits.sh to exit 1, got 0`; exit 1.
- **Control 3 (Syntax error in scenario script):**
  - *Mutation:* Appended invalid bash syntax to `container/scenarios/api-concurrency-and-time.sh`.
  - *Observed locus:* `tests/test_scenario_tokens.py::test_api_scenarios_syntax_valid` FAILED with `AssertionError: Syntax error in ...`; exit 1.

All mutations were restored before capturing final gate logs.

## TEST SIGN-OFF

    claim            Hardcoded API token removed from all scenario scripts, container/env dynamic resolution with empty fail-loud guard enforced, and verified by persistent tests
    source sha       f979390
    artefact         COMMIT
    host             local — pytest and scenario execution audit
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         live container execution, Docker image build, runtime benchmark
    population       528 tests and 5 subtests; all repository tests collected

    control          behavioural and structural mutations: (1) re-introduce hardcoded token; (2) remove empty token guard; (3) scenario syntax error
    expected locus   (1) tests/test_scenario_tokens.py:35; (2) tests/test_scenario_tokens.py:27; (3) tests/test_scenario_tokens.py:16
    observed locus   same
    signature        (1) AssertionError: Hardcoded token found; (2) AssertionError: Expected api-auth-and-limits.sh to exit 1, got 0; (3) AssertionError: Syntax error; all exit 1

    evidence         docs/evidence/build-116-controls.log sha256 8f47b034c00c16c202ee8052092211421708260ea0bdf77db95425ad4a11ea1f
                     docs/evidence/build-116-pytest.log sha256 e88dfd26c79354198d935152307d81fd782d85fbeda6720cb8c80a5fb400a7ff

    verdict          PASS (token removed, empty token guard verified, syntax valid)
    VERIFIED BY      PENDING — assigned by architect

## Citation gate

    source sha       f979390
    artefact         COMMIT
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 86 near misses
    evidence         docs/evidence/build-116-citations.log sha256 14ca07057949d05005174a1a8bdc443030f6bd1de404947c17de0044b108f378

## Merged-tree verification

    merged with      main at 14c86e1
    result           clean merge; 528 passed + 5 subtests passed, exit 0; citations 0 hard / 86 near, exit 0
