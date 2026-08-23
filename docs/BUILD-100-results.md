# BUILD 100 results — one live forward is genuinely unknown

## Mechanism and safety argument

The facility is a scenario-only Redis wrapper supplied to one explicitly
constructed `Switch`. It does not add an injection branch, environment check,
or dependency to the production switch constructor. The wrapper raises once for
the target ingress write and delegates every other Redis operation unchanged.

The harness requires the exact destructive confirmation phrase, generates a
fresh tenant and compose project, refuses any pre-existing project, records the
project only after creation, and tears down only that recorded project. It marks
the tenant with a one-shot token and emits `FAULT_INJECTION_ACTIVE` before
arming. The active and observed records use writer `fault-injection`, so the
synthetic path is visible in the same custody stream as the switch records.

These choices satisfy the four constraints: accidental activation requires a
deliberate phrase and a newly-owned project; activation is loud; shipped switch
construction is inert; and the helper refuses a tenant without the run's token
marker and ownership check.

## Live result

The lab rerun used source `713802e`, fresh tenant `bus100-1787525055-2919997`,
and no other h-flock tenant. The immutable custody snapshot contains these
exact records:

    {"module":"fault_injection","event":"sent","writer":"fault-injection","stream_id":"bce0f7dfe50341e89dccbd2a549c1443","source":"fault-src","destination":"fault-dst"}
    {"module":"switch","event":"popped","writer":"fault-injection","stream_id":"bce0f7dfe50341e89dccbd2a549c1443","source":"fault-src","destination":"fault-dst"}
    {"module":"switch","event":"forward_unknown","writer":"fault-injection","stream_id":"bce0f7dfe50341e89dccbd2a549c1443","source":"fault-src","destination":"fault-dst","reason":"ingress write outcome UNKNOWN after BUILD100 deliberate missing ingress reply"}

The conservation executable consumed the live ledger, custody log, dead queue,
ingress queue, and injection-window captures. Its immutable output was:

    RECONCILE sent=1 delivered_once=0 duplicates=0 dead=0 stranded=0 indeterminate=1 lost_attributed=0 lost_unexplained=0
    INDETERMINATE_FORWARD 1 bce0f7dfe50341e89dccbd2a549c1443

The process returned rc5. No loss was reported, no duplicate was reported, and
no retry was performed. The captured ingress and dead queues were empty, so the
UNKNOWN was not later settled by a committed ingress or terminal dead copy.

The capture also retained the generated tenant, compose project, and container
identity. The harness now refuses before reconciliation if required artifacts
are empty, if the custody stream lacks the run's ledger stream id and
forward_unknown, or if the container label does not match the project created
by this invocation. Empty queue snapshots remain valid and are checked for
presence rather than non-zero size.

## Shapes not reached

This build intentionally reaches only forward_unknown. A provable control-port
Popen rejection still needs a live process-spawn failure; desired-state write
UNKNOWN needs a live Redis reply-loss boundary; and the partial control outcome
needs acknowledged earlier work followed by that provable kick rejection.
Those remain unit-controlled and are not claimed live here.

## TEST SIGN-OFF

    claim            a deliberately assembled live switch can emit forward_unknown and conservation carries it as INDETERMINATE_FORWARD without inventing loss or retrying
    source sha       506a8e5
    artefact         COMMIT plus immutable live snapshots
    host             lab 172.16.0.14 — correctness tenant only
    command          bash container/scenarios/fault-forward-unknown.sh I_UNDERSTAND_THIS_INJECTS_AND_DESTROYS_A_TENANT
    exit status      0, read unpiped

    EXCLUDED         control-port Popen failure, desired-state Redis reply loss, partial control outcome, broadcast fault injection, performance measurement
    population       one live envelope; one generated tenant; one forward fault

    control          one-shot target-ingress reply refusal in the deliberately constructed Redis wrapper
    expected locus   switch/service.py forward_unknown, then reconcile-unicast.py rc5 and INDETERMINATE_FORWARD
    observed locus   same
    signature        live custody forward_unknown; RECONCILE indeterminate=1 lost_unexplained=0; process rc5

    evidence         docs/evidence/build-100-713802e-custody.log sha256 043b06a187c24570ef63b20dca3bbbd7d901900cdafa5a78a75a35afa6122fc3
                     docs/evidence/build-100-713802e-reconcile.log sha256 7cc43a6440fede2029dce6c1d2f85cccc87e0357135919db158cfa52129b685f
                     docs/evidence/build-100-713802e-ledger.tsv sha256 15e9e123bdeee8f0ee915ac59cc7b83322652ee47613633cc4ddf3224fccfac0
                     docs/evidence/build-100-713802e-dead.jsonl sha256 01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b
                     docs/evidence/build-100-713802e-ingress.jsonl sha256 01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b
                     docs/evidence/build-100-713802e-injections.tsv sha256 01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b
                     docs/evidence/build-100-713802e-setup.log sha256 57649a4232d3e3622ce37aba890e66467057a8b52595e7bdb2816aef04a5d3e4
                     docs/evidence/build-100-713802e-run-identity.txt sha256 51fcc813f6385cb01ca0465b9c38f76964f1d93ffdfb1b8065aeafe4c3711b27

    verdict          PASS
    VERIFIED BY      api — author of the change? NO

## Gate results

    command          python3 -m pytest -q
    result           502 passed, 5 subtests passed; exit 0
    evidence         docs/evidence/build-100-713802e-pytest.log sha256 580224b0d1d8b5c1b09783c5a3bfd392396433774c8fa8951232aa96a768c39c
    command          python3 tools/check_citations.py
    result           0 hard failures, 77 near misses; exit 0
    evidence         docs/evidence/build-100-713802e-citations.log sha256 a945cdaa8109a1805c3ac40fe0a464342250a2b71488e30e894c93e1d1d9c95e
