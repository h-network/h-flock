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

The lab run used source `713802e`, a fresh generated tenant, and no other
h-flock tenant. The immutable custody snapshot contains these exact records:

    {"module":"fault_injection","event":"sent","writer":"fault-injection","stream_id":"c7d88f8abb4348769c8e443f8ec98cb2","correlation_id":"51d76bd064924c1a97c6bf348d0ad8e9","source":"fault-src","destination":"fault-dst"}
    {"module":"switch","event":"popped","writer":"fault-injection","stream_id":"c7d88f8abb4348769c8e443f8ec98cb2","correlation_id":"51d76bd064924c1a97c6bf348d0ad8e9","source":"fault-src","destination":"fault-dst"}
    {"module":"switch","event":"forward_unknown","writer":"fault-injection","stream_id":"c7d88f8abb4348769c8e443f8ec98cb2","correlation_id":"51d76bd064924c1a97c6bf348d0ad8e9","source":"fault-src","destination":"fault-dst","reason":"ingress write outcome UNKNOWN after BUILD100 deliberate missing ingress reply"}

The conservation executable consumed the live ledger, custody log, dead queue,
ingress queue, and injection-window captures. Its immutable output was:

    RECONCILE sent=1 delivered_once=0 duplicates=0 dead=0 stranded=0 indeterminate=1 lost_attributed=0 lost_unexplained=0
    INDETERMINATE_FORWARD 1 c7d88f8abb4348769c8e443f8ec98cb2

The process returned rc5. No loss was reported, no duplicate was reported, and
no retry was performed. The captured ingress and dead queues were empty, so the
UNKNOWN was not later settled by a committed ingress or terminal dead copy.

## Shapes not reached

This build intentionally reaches only forward_unknown. A provable control-port
Popen rejection still needs a live process-spawn failure; desired-state write
UNKNOWN needs a live Redis reply-loss boundary; and the partial control outcome
needs acknowledged earlier work followed by that provable kick rejection.
Those remain unit-controlled and are not claimed live here.

## TEST SIGN-OFF

    claim            a deliberately assembled live switch can emit forward_unknown and conservation carries it as INDETERMINATE_FORWARD without inventing loss or retrying
    source sha       713802e
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

    evidence         docs/evidence/build-100-713802e-custody.log sha256 c928a6b47b4d3935b153622e845c624ba65a2017e8e1672b976a76796c918bc0
                     docs/evidence/build-100-713802e-reconcile.log sha256 8f9ada18d16ac83757ae4cf688b121a3969a74c341b148413fb3ebe000b9d5ac
                     docs/evidence/build-100-713802e-ledger.tsv sha256 175e2fa04dd5c440b856e2b65a7e4c2f8c78fc748033a09a98ffbb5b633d6426
                     docs/evidence/build-100-713802e-dead.jsonl sha256 8ce8c4e6e7d7a9858043090a44f578be650fc8bb78fa3d18fd53cd22f50557c2
                     docs/evidence/build-100-713802e-ingress.jsonl sha256 8dca85f42a7518bd5f5b2353f0c5b1aa206977e98d13b8c1fc9fa2151b4828f4
                     docs/evidence/build-100-713802e-injections.tsv sha256 4caf6112df237d12ffd3fbc4d2518a08945dec2332ab05229a20efccad323e03
                     docs/evidence/build-100-713802e-setup.log sha256 8b8c0b58d5a44fb77ea5486d26b807b3695a63423bcc0c3b29114707db750a1b

    verdict          PASS
    VERIFIED BY      PENDING — assigned by architect

## Gate results

    command          python3 -m pytest -q
    result           502 passed, 5 subtests passed; exit 0
    evidence         docs/evidence/build-100-713802e-pytest.log sha256 580224b0d1d8b5c1b09783c5a3bfd392396433774c8fa8951232aa96a768c39c
    command          python3 tools/check_citations.py
    result           0 hard failures, 77 near misses; exit 0
    evidence         docs/evidence/build-100-713802e-citations.log sha256 a945cdaa8109a1805c3ac40fe0a464342250a2b71488e30e894c93e1d1d9c95e
