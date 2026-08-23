# BUILD 102 results — partial control damage is visible but recoverable

## Live method

The scenario created tenant `bus102-1787526448-2924790` and ran the real
`flock.port host` control path. Its Redis client allowed the StopAgent roster
`hdel`, then raised a connection error on the following resource `delete`.
The injector was bound to the tenant marker and all synthetic records used
writer `fault-injection`; no source production switch or control code contains
an injection check. The harness refused pre-existing projects and tore down
only the project it recorded as created.

The immutable snapshot reports the surviving state exactly:

    STATE roster=absent
    STATE resources=present
    STATE delivery_lock=present
    STATUS_BEGIN
      architect   idle      —                                  no activity yet
    STATUS_END
    PEERS_BEGIN
    PEERS_END
    START_RESULT roster=present
    START_RESULT resources=present

Thus `office status` shows the remaining architect as idle, while `office
peers` shows no peer. The half-removed `sme-2` is not displayed as broken; it
simply disappears. A subsequent StartAgent for the same name succeeds in the
desired-state opener and republishes the roster, while the residue resources
and delivery lock were still present. That is silent success onto corrupted
state, not a plainly visible failure.

The live custody record is:

    {"ts":"2026-08-23T23:07:48.991Z","module":"control","event":"stop_agent_incomplete","writer":"fault-injection","correlation_id":"ea2c55e49af54e1fbaeb0eda1394f591","destination":"sme-2","reason":"acknowledged: roster row removed; agent resource purge outcome UNKNOWN after BUILD102 deliberate resource purge reply loss"}

This is the truthful boundary: the roster removal is acknowledged and the
resource purge is UNKNOWN. The result is not a generic failure, and no claim
is made about whether Redis committed the purge.

## Verdict

Desired-state atomicity is warranted. The record is truthful, but it is not
sufficient: the operator-visible status hides the damaged agent, peers is
empty, and StartAgent reports success while stale resources and a delivery lock
remain. A Lua transaction (or equivalent atomic mechanism) should be evaluated
as a follow-up; this spike deliberately does not write it.

## Sign-off

    source sha       f3484e3
    claim            a live partial StopAgent failure is visible in custody but can look healthy and accept a later StartAgent
    expected locus   control opener between roster hdel and resource purge
    observed locus   same; stop_agent_incomplete with acknowledged roster removal and UNKNOWN purge
    evidence         docs/evidence/build-102-custody.log sha256 8e76ffc45705d1a4b0f613c76117775636790342242bb39a981164aea111da48
                     docs/evidence/build-102-snapshot.txt sha256 306480e42c71133687490cbb8c88798f4e7dfc5bd225d75f8ddbccd477166612
                     docs/evidence/build-102-run-identity.txt sha256 d89a719c74c3092539d7acd56242bd775da96d7159221492543d3871112759e3
                     docs/evidence/build-102-injector.log sha256 054823b3756759601b09cdac9c0ea16149ec9c96759bae7212d9f64924373a4d
                     docs/evidence/build-102-setup.log sha256 f4e8239069d91637e7fc6b8fd0491011a25179d40e335e38cc515e2321fdcc7d
    verdict          PASS — atomicity warranted; no Lua written
    VERIFIED BY      api — author of the change? NO

## Gates

    command          python3 -m pytest -q
    result           507 passed, 5 subtests passed; exit 0
    command          python3 tools/check_citations.py
    result           0 hard failures, 77 near misses; exit 0
