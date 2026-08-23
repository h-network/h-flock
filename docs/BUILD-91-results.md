# BUILD 91 results — control says what it did

## Result

- `StartAgent`, `StopAgent`, `PauseAgent`, and `ResumeAgent` emit one of three
  desired-state outcomes: `*_accepted` when every desired write committed,
  `*_incomplete` when only a subset committed or an inline actual-state callback
  failed, and `*_failed` when no write committed. Incomplete outcomes name the
  committed subset and the failing write or side effect, then still dead-letter.
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
`982dc0a1124f9276594fa3cdb5dea4671bb2e1cf`. Exact output is retained in the
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
6. Partial desired-state tracking disabled: both StartAgent and StopAgent
   partial-write tests lose the committed subset and fail at their expected
   exception locus; exit 1.
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

    claim            control records distinguish accepted desired state, explicitly named partial commits, and no-write failure without claiming actual state; setup seeds canonical accounts read identically by client and fabric with legacy absence permissive; token-auth Claude does not alert absent while genuine absence does
    source sha       982dc0a1124f9276594fa3cdb5dea4671bb2e1cf
    artefact         COMMIT
    host             local — canonical Redis state and control/tmux boundaries used deterministic test doubles; setup/entrypoint persistence was inspected by focused executable tests
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container image/build, accept.sh, live tenant, real tmux windows, real vendor authentication, and revoked-token detection
    population       487 tests and 5 subtests; all repository tests collected

    control          ten property mutations listed above
    expected locus   the ten named focused tests above
    observed locus   the same ten focused tests above
    signature        accepted-vs-confirmed mismatches; refused mismatch; fabric/client DID NOT RAISE; callback and partial-write incomplete failures; unexpected absent alert; two legacy refusals; missing default persistence; missing SADD seeding

    evidence         docs/evidence/build-91-982dc0a-controls.log sha256 4046a773ebf0e1d092613c1b5593641a9badbda13aded19780e9e6deb2cc3fb9
                     docs/evidence/build-91-982dc0a-pytest.log sha256 72fab3f11a68fda96fb18a6e229acc0a2e50d085eab987172ca25e2f1195d65d

    verdict          PASS
    VERIFIED BY      PENDING — assigned verifier bus; author of the change? NO

## Citation gate

    source sha       b29599824300e4a02f7bdbd99045cc8f5c8371ca
    artefact         COMMIT
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 54 near misses
    evidence         docs/evidence/build-91-b295998-citations.log sha256 7f130293467df13a9a22748cfc93b163471d1fc3d87772444e6ef62be3f491e6
