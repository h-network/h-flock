# BUILD 110 results — RESP EVAL and the capable double

## Result

`flock.bus.resp.Redis.eval(script, numkeys, *keys_and_args)` now emits the
ordinary RESP2 `EVAL script numkeys key... arg...` request through `_command`.
The Build 103 Lua and its roster-before-cause ordering are unchanged.

The two doubles which exercised that Lua declare themselves with
`__resp_double__ = True`. A persistent AST test discovers marked doubles by
that declaration, asserts that it found at least two, and refuses any public
method absent from the production `resp.Redis` class. The production client
also gained the ordinary `GETDEL` command already exposed by the combined
tmuxhost/control double.

⚠ Unit tests establish the wire shape and the structural surface only. They do
not close the live defect. Acceptance must demonstrate that a real post-boot
hire creates desired state and a window before this build is believed.

## TEST SIGN-OFF

    claim            RESP Redis exposes EVAL with exact RESP2 shape, and marked RESP doubles cannot expose a larger public method surface
    source sha       e53f7d6
    artefact         COMMIT
    host             local
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         live tenant acceptance; StartAgent window creation against the packaged client
    population       521 tests and 5 subtests; all repository tests collected

    control          (1) add only_on_the_double to a marked double; (2) rename production eval to _eval
    expected locus   tests/test_resp.py structural assertion
    observed locus   (1) RecordingRedis.only_on_the_double; (2) RecordingRedis.eval and MockRedis.eval; both exit 1
    evidence         docs/evidence/build-110-controls.log sha256 615865c40baf5e188a6679bb9dafd8bdaef4d92105034b938eb9846d1256f3a3
                     docs/evidence/build-110-pytest.log sha256 7ebb0c3710d491e5a9da72dbb8425ba5bb59e425076cd248bfc7c84f1a4016d5

    verdict          SMOKE — unit and structural properties hold; live acceptance is required
    VERIFIED BY      PENDING — assigned by architect

## Citation gate

    source sha       e53f7d6
    artefact         COMMIT
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 86 near misses
    evidence         docs/evidence/build-110-citations.log sha256 a0762c46aa67231bff796e73207898ef24cee82a545e27424dd940920398d767
