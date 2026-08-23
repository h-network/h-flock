# BUILD 91 results — control says what it did

## Result

- `StartAgent`, `StopAgent`, `PauseAgent`, and `ResumeAgent` emit one of three
  reader-facing outcomes: `*_confirmed` after desired and actual state agree,
  `*_incomplete` when desired state committed but the actual-state callback
  failed, and `*_failed` for a pre-mutation refusal. Incomplete outcomes name
  both the committed state and failed side effect, then still dead-letter.
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
account set and three-outcome record model above are the corrections.

## Negative controls

All nine controls ran against source
`64744b1e6cb31ba8547cba013af01e602a876652`. Exact output is retained in the
immutable controls snapshot named in the sign-off.

1. `confirmed` → `completed`: all four cases in
   `test_control_openers_record_confirmed_outcome` fail with the event mismatch;
   exit 1.
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
6. Token recognition disabled:
   `test_claude_profile_token_is_authenticated_without_credentials_file`
   observes an unexpected credential alert with `status: absent`; exit 1.
7. Missing canonical set changed from permissive `None` to empty configured
   set: both fabric and client legacy compatibility tests reject the profile;
   exit 1.
8. Single-account setup stopped persisting `default`:
   `test_setup_persists_complete_account_list_even_for_single_account` fails at
   the missing setup output; exit 1.
9. Entrypoint seeding changed from `SADD` to `SET`:
   `test_entrypoint_seeds_canonical_accounts_before_unsetting_startup_env`
   fails at the set-seeding locus; exit 1.

## TEST SIGN-OFF

    claim            control records distinguish confirmed, incomplete, and pre-mutation failure; setup seeds canonical accounts read identically by client and fabric with legacy absence permissive; token-auth Claude does not alert absent while genuine absence does
    source sha       64744b1e6cb31ba8547cba013af01e602a876652
    artefact         COMMIT
    host             local — canonical Redis state and control/tmux boundaries used deterministic test doubles; setup/entrypoint persistence was inspected by focused executable tests
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container image/build, accept.sh, live tenant, real tmux windows, real vendor authentication, and revoked-token detection
    population       483 tests and 5 subtests; all repository tests collected

    control          nine property mutations listed above
    expected locus   the nine named focused tests above
    observed locus   the same nine focused tests above
    signature        four completed mismatches; refused mismatch; fabric/client DID NOT RAISE; four incomplete-vs-failed mismatches; unexpected absent alert; two legacy refusals; missing default persistence; missing SADD seeding

    evidence         docs/evidence/build-91-64744b1-controls.log sha256 ed0d73b996698d489ed714d114e741672169a4e8ea13da72a795061582af6115
                     docs/evidence/build-91-64744b1-pytest.log sha256 8272e39fb1dcb92fdcc90301a9145216d04d0f61d68190fdde3fd15e0aaf5e9e

    verdict          PASS
    VERIFIED BY      PENDING — assigned verifier bus; author of the change? NO

## Citation gate

    source sha       64744b1e6cb31ba8547cba013af01e602a876652
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 52 near misses after the amended living citations were refreshed
    evidence         docs/evidence/build-91-64744b1-citations-v2.log sha256 e0b463b17d6d1c11fa6ba2219a55d4797bd65e787cc28a2a3dbdcf6ace7611a3
