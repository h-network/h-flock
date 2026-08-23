# BUILD 101 results — acceptance console hygiene

## Result

`--keep` continues to retain the console because it is part of the live tenant
the operator requested. Ownership is no longer silent: the `kept:` line names
the container, the console PID, and the exact `kill <pid>` command that stops
the host process. When no console was started, it says so instead of inventing
an owner or PID.

The console server now receives `API_TOKEN` and `HFLOCK_SECRET` through its
environment, using the defaults already implemented by `server.py`. Neither
credential nor its flag name appears in the retained process's argv. The rest
of the launch line contains only listen address, port, API URL, and session URL;
no other secret was found there. `clients/` was untouched.

## Behavioural controls

The focused test runs the real `accept.sh` through a disposable fake tenant
boundary, starts a real retained host process, reads its inherited environment
and `/proc/<pid>/cmdline`, and kills that exact PID afterward. It is not a
source-text assertion.

- Restoring the old container-only `kept:` line fails at the ownership output
  assertion while the console process is genuinely alive.
- Restoring `--token "$TOKEN" --secret "$SECRET"` fails at the real process
  argv assertion with `token-sentinel` visible.

This does not claim a live Docker acceptance run. Per the spec, `acceptance`
will confirm the merged script on the lab; that live arm remains excluded here.

## TEST SIGN-OFF

    claims           --keep names the retained console PID and stop command; console credentials are inherited but absent from argv
    source sha       b0ce784aab68dd6529fd5a254629d733522fb222
    artefact         COMMIT
    host             local — disposable fake tenant boundary plus real retained host process and /proc
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         Docker image/build, live tenant, real console HTTP behavior, Playwright flows, post-merge lab acceptance
    population       499 tests and 5 subtests; all repository tests collected

    controls         remove PID/kill ownership disclosure; restore credentials as server argv flags
    expected loci    retained ownership output; /proc console argv
    observed loci    tests/test_accept.py:114; tests/test_accept.py:125
    signatures       old kept line observed; token-sentinel observed in cmdline; each exit 1

    evidence         docs/evidence/build-101-b0ce784-controls.log sha256 6ec5c69b0d5d0b2b78940a4bf220ad69cefea3669c9c840a7f48cc37d37f828a
                     docs/evidence/build-101-b0ce784-pytest.log sha256 344542484547525e2c9839b681431bb6e6c812ada5b0daeaccbaff6153579c89

    verdict          PASS for the process boundary; live acceptance remains explicitly excluded
    VERIFIED BY      api — author of the change? NO

## Citation gate

    source sha       b0ce784aab68dd6529fd5a254629d733522fb222
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 77 near misses
    evidence         docs/evidence/build-101-b0ce784-citations.log sha256 85aa5ee349d52d6d940bfa2506f815816adde5ba228ddca8cc2279b25f4104a1
