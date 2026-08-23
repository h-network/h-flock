# BUILD 91 results — control says what it did

## Result

- `StartAgent`, `StopAgent`, `PauseAgent`, and `ResumeAgent` now emit a
  kind-specific `*_confirmed` record after completing their mutation. Any
  exception emits the matching `*_failed` record, with the target agent,
  correlation id when present, and refusal reason, before the runner
  dead-letters the envelope.
- The office client and control opener both reject an unknown `--profile` and
  list the account config directories that exist. The client refuses before
  calling `send`; the fabric repeats the validation for non-office producers.
- A non-empty per-profile `CLAUDE_OAUTH_TOKEN_<PROFILE>` is recognized as the
  credential that `tmux.ops` injects into that profile's window. A Claude
  profile with neither token nor credentials file still alerts `absent`.

## Negative controls

All controls ran against source `702b8845986201a321cf99b7862eceedc1e0bd69`.
The exact outputs below are quoted from the immutable controls snapshot named
in the sign-off.

1. **Confirmed outcome:** changed the emitted suffix from `confirmed` to
   `completed`. Expected and observed locus:
   `test_control_openers_record_confirmed_outcome`. The snapshot records:
   `AssertionError: assert 'start_agent_completed' == 'start_agent_confirmed'`
   and the equivalent failure for all four openers; exit 1.
2. **Refused outcome:** changed the emitted suffix from `failed` to `refused`.
   Expected and observed locus:
   `test_refused_start_records_failure_before_dead_letter`. The snapshot
   records: `AssertionError: assert 'start_agent_refused' ==
   'start_agent_failed'`; exit 1.
3. **Fabric profile validation:** disabled the opener's known-account
   comparison. Expected and observed locus:
   `test_start_agent_refuses_unknown_profile_and_lists_available`. The snapshot
   records: `Failed: DID NOT RAISE ValueError`; exit 1.
4. **Client profile validation:** disabled the office client's known-account
   comparison. Expected and observed locus:
   `test_hire_refuses_unknown_profile_at_client_with_available_accounts`. The
   snapshot records: `Failed: DID NOT RAISE SystemExit`; exit 1.
5. **Token authentication:** disabled recognition of the per-profile token.
   Expected and observed locus:
   `test_claude_profile_token_is_authenticated_without_credentials_file`. The
   snapshot records an unexpected credential alert with `"status":"absent"`;
   exit 1.

## TEST SIGN-OFF

    claim            lifecycle outcomes are recorded, unknown profiles are refused at client and fabric, and token-authenticated Claude profiles do not alert absent while genuinely credentialless profiles do
    source sha       702b8845986201a321cf99b7862eceedc1e0bd69
    artefact         COMMIT
    host             local — filesystem account discovery used isolated temporary homes; Redis and tmux boundaries used deterministic test doubles
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container image/build, accept.sh, live tenant, real tmux windows, and real vendor authentication
    population       474 tests and 5 subtests; all repository tests collected

    control          five property mutations: confirmed event name, failed event name, fabric profile comparison, client profile comparison, and token recognition
    expected locus   the five named tests above
    observed locus   the same five tests above
    signature        four *_completed mismatches; *_refused mismatch; DID NOT RAISE ValueError; DID NOT RAISE SystemExit; unexpected absent alert

    evidence         docs/evidence/build-91-702b884-controls-v2.log sha256 12a5c78d5d0d5c3a469a3faa56262290dff84e00c33ddef51c9f3cd5da717988
                     docs/evidence/build-91-702b884-pytest.log sha256 2a25f7bb4f2e0105be0318d7b56751f4104bc3108a010204a3c0b25764030ff1

    verdict          PASS
    VERIFIED BY      PENDING — author of the change? NO

## Citation gate

    source sha       702b8845986201a321cf99b7862eceedc1e0bd69
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 50 near misses after the living NAMING-tmux citations were refreshed
    evidence         docs/evidence/build-91-702b884-citations-v3.log sha256 f2a20e4ba518a35f607cd7535f8ad598952cd80ae44c1e5dd1307f83b0bdc5d1
