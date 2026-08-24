# BUILD 115 results — verifying the packet-switching harness

**Branch tested: `bus/build-114-packet-switching-harness` at `f977869`** — confirmed
this is exactly the branch tip, not behind it, at verification time. **Not
merged to `main`.** Host: the lab (`172.16.0.14`). No rate is quoted anywhere
below — this is a correctness verification, per `BUILD-CONVENTION` §3.0.

Verified against `docs/BUILD-114-packet-switching-harness.md` (the spec).
`docs/BUILD-114-results.md` was treated as a claim to check, not a description
to confirm.

## Check 1 — steady mode is clean

`CONTAINER=... TENANT=build115v-0824-1420 POD=acme bash container/scenarios/packet-switching.sh --mode steady --count 10 --rounds 2`, own tenant and project.

```
PACKET_QUEUE_DEPTH ingress_plus_egress=0 drained=1
PACKET_COUNTS submitted=20 opened=20 stray=0
PACKET_STAGES sent=20 popped=20 forwarded=20 received=20 opened=20
PACKET_RESULT rc=0 reason=clean
```
`rc0`, no losses, no duplicates, no strays. **No `diagnostic-*` files were
written** — confirmed by listing the work directory immediately after: only
`custody.log`, `ledger.tsv`, and three empty `dead.jsonl`/`ingress.jsonl`/
`injections.tsv` placeholders. Retention-on-green does not happen, as the spec
requires.

## Check 2 — the three REDs, reproduced independently

Built three minimal `custody.log` fixtures from scratch (not reused from
`tests/test_packet_switching.py`, though the same shape) and ran the harness's
own `--reconcile-only` judge against each:

| mutation | expected (results doc) | observed here |
|---|---|---|
| `sent`, no `opened` | rc1 | `PACKET_RESULT rc=1 reason=conservation_failure`, exit 1 |
| `sent` + two `opened` | rc2 | `PACKET_RESULT rc=2 reason=conservation_failure`, exit 2 |
| `opened` for an unsent stream | rc3 | `STRAY_OPENED verify-stray-nosend` / `PACKET_RESULT rc=3 reason=stray`, exit 3 |

All three match the results doc's claim exactly, reproduced by an independent
fixture, not by trusting the pytest run that shipped with the branch.

## Check 3 — the failure capture actually fires

Needed a genuine non-zero **live** run without touching the excluded 100×2
burst. Used the real `flock.bus.doors.send()` path to queue one envelope
(`source=architect`, `destination=bench-1`) via `docker exec` **without** the
`/proc/1/fd/1` redirect the harness's own sender uses — so this call's own
`sent` custody line never reaches `docker logs`, while the tenant's real,
already-running api-port opener still processes and delivers it, emitting a
genuine `received`/`opened` pair that **does** reach `docker logs`. That
produces a real stray with no fixture involved. Re-ran the harness in steady
mode; it picked up this stray alongside a fresh clean batch:

```
PACKET_COUNTS submitted=60 opened=61 stray=1
STRAY_OPENED 6672a488b73c4088a1035cd59f7fcbe6   <- exactly the injected stream_id
PACKET_RESULT rc=3 reason=stray
PACKET_DIAGNOSTICS retaining work=...
PACKET_DIAGNOSTICS missing=diagnostic-queues.tsv
PACKET_DIAGNOSTICS status=incomplete
```

All six `diagnostic-*` files plus `diagnostic-sha256.txt` were present in the
work directory **before teardown** (confirmed by listing it while the tenant
container was still up) — but see the finding below: one of the six is
*always* empty on a live non-zero run, which is a genuine harness property,
not a check-3 failure on my part.

⚠ **Unprompted finding, not one of the four checks, discovered while
satisfying check 3**: `diagnostic-queues.tsv` reports ingress/egress `LLEN`
per key, but the harness requires `drained=1` (all queues empty) as a
precondition **before it will ever call `judge()`/`capture_diagnostics` at
all** (`packet-switching.sh:143`). Redis deletes a list key entirely once it
empties, so `scan_iter` over `*:ingress`/`*:egress` finds nothing at capture
time, on *every* non-zero live run, not just this one — `diagnostic-queues.tsv`
is structurally guaranteed to be empty whenever it is produced. This is a real
property of the harness as written, reported precisely rather than glossed
into "the six files were all produced."

## Check 4 — the check that guards the others

**Case A — an artifact empty.** Already demonstrated, live, not engineered:
`diagnostic-queues.tsv` above. Correctly triggered `PACKET_DIAGNOSTICS
missing=diagnostic-queues.tsv` and folded into overall `status=incomplete`.

**Case B — a traceback at the END, after valid content.** Injected a second
stray the same way, then re-ran the harness with a `docker` wrapper placed
earlier in `PATH` that passes every call through to the real binary **except**
`docker logs`, where it appends a synthetic Python traceback after the real
output. `diagnostic-container.log` ended up as 636 real lines of genuine
container log (redis boot, custody records, health checks) followed by:

```
Traceback (most recent call last):
  File "synthetic.py", line 1, in <module>
    raise RuntimeError("BUILD-115 check 4: deliberately corrupted capture")
RuntimeError: BUILD-115 check 4: deliberately corrupted capture
```

Result: `PACKET_DIAGNOSTICS invalid=diagnostic-container.log`, folded into
overall `status=incomplete` — confirmed by inspecting the actual file (first 3
and last 6 lines quoted in the evidence), not by trusting the harness's own
claim. **Both cases report `status=incomplete`**, as the spec requires. The
grep pattern used by the harness (`Traceback \(most recent call last\):`)
catches the traceback regardless of its position in the file — a top-only
check would have missed this, and the harness's is not top-only.

Aside, unrelated to any of the four checks: `diagnostic-container.log`'s first
line in both live runs was `entrypoint.sh: line 23: .../custody.jsonl:
Permission denied` — present at container boot, not something either injected
stray triggered. Noting it; not investigated further, out of scope for this
verification.

## What this run did not touch

The 100×2 burst and its five-envelope loss — explicitly out of scope, the
operator's call. Wiring into `accept.sh` — a separate decision per the spec.
No fix was made to anything found.

## TEST SIGN-OFF

    claim            the packet-switching harness (bus/build-114 at f977869) behaves as BUILD-114-results.md claims: clean on a steady run, red with the correct rc for loss/duplicate/stray, retains a complete diagnostic bundle only on a non-zero live run before teardown, and correctly marks that bundle incomplete when one artifact is empty or ends in a traceback after valid content
    source sha       f977869fb6a0d6e3bd4e0d67a01feeb5705357fa (bus/build-114-packet-switching-harness, confirmed at branch tip, not merged to main)
    artefact         WORKING TREE, checked out at that exact commit on the lab
    host             lab 172.16.0.14 — correctness only, no rate quoted
    command          container/scenarios/packet-switching.sh, both --mode steady and --reconcile-only, per check above
    exit status      0 (check 1), 1/2/3 (check 2, one per mutation), 3 (checks 3-4), each read unpiped

    EXCLUDED         the 100x2 burst and its unexplained loss; wiring into accept.sh; any port/terminal/application layer (the harness's own stated boundary)
    population       4 of 4 checks in the spec; all four independently reproduced, none trusted from the results doc alone

    control          check 2: three custody.log mutations (removed opened, duplicate opened, stray opened) built from scratch
                     check 3/4: one real stray injected via send() with an invisible sent record (twice, for checks 3 and 4 separately); check 4 case B also used a docker-logs shim appending a trailing traceback
    expected locus   judge()'s PACKET_RESULT line and exit code; capture_diagnostics' PACKET_DIAGNOSTICS status line
    observed locus   same — rc1/rc2/rc3 and PACKET_RESULT matched exactly; PACKET_DIAGNOSTICS status=incomplete fired for both check-4 cases
    signature        PACKET_RESULT rc=1/2/3 per mutation; PACKET_DIAGNOSTICS missing=diagnostic-queues.tsv and invalid=diagnostic-container.log, both folding into status=incomplete

    evidence         docs/evidence/build-115-f977869/ — check1-steady/, check2-fixtures/{loss,dup,stray}/, check3-stray-live/, check4-corrupted-capture/
                     custody.log sha256, per check:
                       check1: d406c2a9306dae5e0093aa6a45cd08ebdf9e96b71481ba6188d2d7db5e485b4e
                       check2/loss: 75a169e2dfe962bb08e901d21eb9cadf4aeb778908bbf2c5a7e1cf2cd8a6a6b0
                       check2/dup: 922f09f16826efb5a9b0d63d2076b519240ec97a90427214bc3f6096a0005293
                       check2/stray: accc0e6994877beec3cd6986d82416bc84a907cf07f81203bfa9769b2ce139ea
                       check3: 58509eb60ba72677f9c480d161a77712214bd93272461409c7f1431520c8e593
                       check4 diagnostic-container.log: 65cbd689bce81a10b5e27de9d0c261bc0584ebfffd30337e41d299287361a2f5

    verdict          PASS — all four checks confirmed as specified, plus one unprompted structural finding (diagnostic-queues.tsv is always empty on a live non-zero run)
    VERIFIED BY      acceptance — author of the change? NO

    DESTRUCTIVE      identity this run CREATED: tenant build115v-0824-1420 (project h-flock-build115v-0824-1420), own namespace only
                     what teardown touches: that project only, via `docker compose -p h-flock-build115v-0824-1420 down -v`
                     protected names refused: none encountered; the four pre-existing hvab-* containers were not touched (confirmed by container count before/after: 4/6/8 both times)
