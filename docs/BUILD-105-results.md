# BUILD 105 results — the monitor stops saying things that are false

## Result

1. **Retraction of Recovered Credential Alerts (`src/flock/watchdog/service.py:318-335`, `docs/LLD-watchdog.md:191-208`):**
   - When a credential recovers from an alerted state (`absent`, `expiring`, `expired`, `unknown`) to healthy (`status: "present"`), the watchdog emits a retraction record with `status: "present"` and `expires_ts` to the alert stream, and deletes the `<account>:<cli>` field from `credential.alerted`.
   - Steady-state healthy credentials on fresh startup or subsequent passes emit nothing.
   - Documented in `docs/LLD-watchdog.md` Section 5 with the rationale per `BUILD-38-durable` §2: emitting `status: "present"` enables stream consumers and console monitors to determine current state by taking the latest record per `(account, cli)`, as cursor-based clearable alerts do not exist in the append-only stream.

2. **agy Token Accounting Correction (`docs/CONTRACTS.md:525-538`, `docs/BUILD-88-results.md:21-24`, `src/flock/office/cli.py:234,747`):**
   - Corrected the agy token measurement claim: agy writes per-conversation transcripts under `brain/<id>/.system_generated/logs/`, but h-flock does not collect them; whether those transcripts carry token counts is unverified.
   - `office status` activity column reads `not collected (agy)` (was `not measurable (agy)`).
   - `office usage` model reads `not collected` (was `not measurable`), and `--json` output carries `"collected": false` on uncollected rows.

## Negative Controls (Falsifiability)

- **Control 1 (Credential retraction emission on recovery):**
  - *Mutation:* In `src/flock/watchdog/service.py`, revert recovery to the previous behavior (silent `hdel` without emitting alert).
  - *Observed locus:* `tests/test_watchdog.py::test_credential_alert_retracted_when_credential_recovers` FAILED with `AssertionError: assert 1 == 2`; exit 1.
- **Control 2 (Office status agy not collected label):**
  - *Mutation:* In `src/flock/office/cli.py`, revert `activity = "not collected (agy)"` to `"not measurable (agy)"`.
  - *Observed locus:* `tests/test_office.py::test_status_names_agy_agent_not_collected` FAILED with `AssertionError: assert 'not collected (agy)' in ...`; exit 1.
- **Control 3 (Office usage agy not collected label):**
  - *Mutation:* In `src/flock/office/cli.py`, revert `"model": "not collected"` to `"not measurable"`.
  - *Observed locus:* `tests/test_usage.py::test_office_usage_names_agy_agent_not_collected` FAILED with `AssertionError: assert 'not collected' in ...`; exit 1.

All mutations were restored before capturing final gate logs.

## TEST SIGN-OFF

    claim            Watchdog emits status=present when credential recovers, and office status/usage/CONTRACTS document agy as not collected
    source sha       1eaecf6
    artefact         COMMIT
    host             local — pytest and documentation audit
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         live container execution, Docker image build, runtime benchmark
    population       516 tests and 5 subtests; all repository tests collected

    control          behavioural mutations: (1) silent credential recovery; (2) status agy label revert; (3) usage agy label revert
    expected locus   (1) tests/test_watchdog.py:362; (2) tests/test_office.py:333; (3) tests/test_usage.py:978
    observed locus   same
    signature        (1) AssertionError: assert 1 == 2; (2) AssertionError: assert 'not collected (agy)' in ...; (3) AssertionError: assert 'not collected' in ...; all exit 1

    evidence         docs/evidence/build-105-controls.log sha256 d35809a25611db5de6fc0b4d3e1229ee5b443422a247726731650441478fa17a
                     docs/evidence/build-105-pytest.log sha256 34deb4022d349619aaf13f071660204af536b3e23486525dc20a3cb123e74dc3

    verdict          PASS (behavioural retraction verified and doc sentences asserted by tests)
    VERIFIED BY      PENDING — assigned by architect

## Citation gate

    source sha       1eaecf6
    artefact         COMMIT
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 86 near misses
    evidence         docs/evidence/build-105-citations.log sha256 1ccc9a5e112e319a316aa71b6b47e08c410b78798e019ef2582ad63c189860ad

## Merged-tree verification

    merged with      main at e44688c
    result           clean merge; 516 passed + 5 subtests passed, exit 0; citations 0 hard / 86 near, exit 0
