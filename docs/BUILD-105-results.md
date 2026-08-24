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
   - `tests/test_usage.py::test_agy_uncollected_documentation_bounded_claims` asserts the exact bounded sentences across both `docs/CONTRACTS.md` and `docs/BUILD-88-results.md`.

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
- **Control 4 (Bounded doc claims assertion):**
  - *Mutation:* In `docs/CONTRACTS.md`, replace `"h-flock does not collect it"` with `"h-flock collects it automatically"`.
  - *Observed locus:* `tests/test_usage.py::test_agy_uncollected_documentation_bounded_claims` FAILED with `AssertionError`; exit 1.

All mutations were restored before capturing final gate logs.

## TEST SIGN-OFF

    claim            Watchdog emits status=present when credential recovers, office status/usage/CONTRACTS document agy as not collected, and doc assertions are tested
    source sha       75f5529
    artefact         COMMIT
    host             local — pytest and documentation audit
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         live container execution, Docker image build, runtime benchmark
    population       517 tests and 5 subtests; all repository tests collected

    control          behavioural and doc mutations: (1) silent credential recovery; (2) status agy label revert; (3) usage agy label revert; (4) doc claim mutation
    expected locus   (1) tests/test_watchdog.py:362; (2) tests/test_office.py:333; (3) tests/test_usage.py:978; (4) tests/test_usage.py:1000
    observed locus   same
    signature        (1) AssertionError: assert 1 == 2; (2) AssertionError: assert 'not collected (agy)' in ...; (3) AssertionError: assert 'not collected' in ...; (4) AssertionError; all exit 1

    evidence         docs/evidence/build-105-controls.log sha256 39e5a7c27c68f980a57eea57efd14043fd53822e9eb8f9daf5435c287a0845ad
                     docs/evidence/build-105-pytest.log sha256 48e4a7b2524b3199df3c25b94b25f2ef3d694f0ac2c47cc94bc4c4317bdefcd7

    verdict          PASS (behavioural retraction verified and doc sentences asserted by tests)
    VERIFIED BY      tmux — author of the change? NO

## Citation gate

    source sha       75f5529
    artefact         COMMIT
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 86 near misses
    evidence         docs/evidence/build-105-citations.log sha256 96bcdc5448b4f0d9b59d17aed391bf65459dead1015b48acbd4538206b4ce750

## Merged-tree verification

    merged with      main at e44688c
    result           clean merge; 517 passed + 5 subtests passed, exit 0; citations 0 hard / 86 near, exit 0
