# BUILD 91 results — control says what it did

## Result

- `StartAgent`, `StopAgent`, `PauseAgent`, and `ResumeAgent` emit one of three
  desired-state outcomes: `*_accepted` when every desired write committed,
  `*_incomplete` when a write's outcome is unknown, only a subset was
  acknowledged, or an inline actual-state callback failed, and `*_failed` only
  before any write was attempted. Write exceptions name acknowledged facts and,
  separately, the in-flight write whose outcome is `UNKNOWN`, then dead-letter.
  **Build 91 records what control accepted, not what happened in actual state.**
  Tmuxhost confirmation after asynchronous reconciliation is a separate build.
- `setup.sh` persists the complete configured account list as
  `FLOCK_ACCOUNTS`; entrypoint seeds the canonical tenant Redis set `accounts`
  before unsetting startup state. Office and fabric read that same set. An
  absent set deliberately disables validation so pre-Build-91 tenants remain
  compatible. An account added outside setup (for example by hand-seeding a
  config directory) is not canonical until setup runs again; the visible
  refusal lists the accounts that are canonical.
- A non-empty per-profile `CLAUDE_OAUTH_TOKEN_<PROFILE>` is recognized as the
  credential that `tmux.ops` injects into that profile's window. A Claude
  profile with neither token nor credentials file still alerts `absent`.
  **Known limit:** local token presence cannot reveal a revoked or expired
  token, so that failure remains invisible until a remote authentication probe
  exists.

## Independent refusal and correction

Bus independently reproduced the original five controls, then refused the
product at two loci: filesystem directories classified configured accounts in
both directions incorrectly, and post-commit callback failures were recorded
as whole-operation failures. Both findings were upheld. The canonical Redis
account set corrected the first refusal. Its second read found two remaining
contract errors: partial desired writes still reached `failed`, and a fresh
asynchronous hire reached `confirmed` without a window. The second amendment
withdraws opener confirmation; accepted desired state and explicitly named
partial commits are the corrections above.

## Negative controls

All ten controls ran against source
`cb502be844dad09157a023befeb544a59b26ff82`. Exact output is retained in the
immutable controls snapshot named in the sign-off.

1. `accepted` → `confirmed`: all four cases in
   `test_control_openers_record_accepted_outcome` and the fresh asynchronous
   start case fail with the event mismatch; exit 1.
2. `failed` → `refused`:
   `test_refused_start_records_failure_before_dead_letter` fails with
   `assert 'start_agent_refused' == 'start_agent_failed'`; exit 1.
3. Fabric canonical-account comparison disabled:
   `test_start_agent_refuses_unknown_profile_and_lists_available` reports
   `DID NOT RAISE ValueError`; exit 1.
4. Client canonical-account comparison disabled:
   `test_hire_reads_canonical_accounts_from_redis` reports
   `DID NOT RAISE SystemExit`; exit 1.
5. `incomplete` mislabeled `failed`: all four post-commit callback cases in
   `test_post_commit_side_effect_failure_records_incomplete` fail with the
   exact event mismatch; exit 1.
6. Unknown-write classification removed: acknowledged-prefix, first-write, and
   reply-lost-after-commit probes all lose their `incomplete` record and
   `UNKNOWN` clause at the expected locus; exit 1.
7. Token recognition disabled:
   `test_claude_profile_token_is_authenticated_without_credentials_file`
   observes an unexpected credential alert with `status: absent`; exit 1.
8. Missing canonical set changed from permissive `None` to empty configured
   set: both fabric and client legacy compatibility tests reject the profile;
   exit 1.
9. Single-account setup stopped persisting `default`:
   `test_setup_persists_complete_account_list_even_for_single_account` fails at
   the missing setup output; exit 1.
10. Entrypoint seeding changed from `SADD` to `SET`:
   `test_entrypoint_seeds_canonical_accounts_before_unsetting_startup_env`
   fails at the set-seeding locus; exit 1.

## TEST SIGN-OFF

    claim            control records distinguish accepted desired state, acknowledged facts plus unknown in-flight writes, and pre-write failure without claiming actual state; setup seeds canonical accounts read identically by client and fabric with legacy absence permissive; token-auth Claude does not alert absent while genuine absence does
    source sha       cb502be844dad09157a023befeb544a59b26ff82
    artefact         COMMIT
    host             local — canonical Redis state and control/tmux boundaries used deterministic test doubles; setup/entrypoint persistence was inspected by focused executable tests
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container image/build, accept.sh, live tenant, real tmux windows, real vendor authentication, and revoked-token detection
    population       488 tests and 5 subtests; all repository tests collected

    control          ten property mutations listed above
    expected locus   the ten named focused tests above
    observed locus   the same ten focused tests above
    signature        accepted-vs-confirmed mismatches; refused mismatch; fabric/client DID NOT RAISE; callback and UNKNOWN-write incomplete failures including reply loss after commit; unexpected absent alert; two legacy refusals; missing default persistence; missing SADD seeding

    evidence         docs/evidence/build-91-cb502be-controls.log sha256 b8074a406b16a947358da7f16211c69cca9d2e220f42055b459799e40cf61f60
                     docs/evidence/build-91-cb502be-pytest.log sha256 4b79dd46cabe172cd4a39e1d3027a4c94551083b0928f866013c273a9bcc1bd1

    verdict          PASS
    VERIFIED BY      PENDING — assigned verifier bus; author of the change? NO

## Citation gate

    source sha       d2eca79a0a2d194fecd8d3824bf4359669e4cdde
    artefact         COMMIT
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 54 near misses
    EXCLUDED         the immediately following evidence-binding commit: only this PENDING block is replaced and docs/evidence/build-91-d2eca79-citations.log is added; no product documentation or path citation changes
    evidence         docs/evidence/build-91-d2eca79-citations.log sha256 7f130293467df13a9a22748cfc93b163471d1fc3d87772444e6ef62be3f491e6
