# BUILD 121 results — proving script 1 live, all four checks

**Base: `main` at `a242393`.** Host: the lab, correctness only — no rate
quoted. Nothing modified. `bus/build-120-script-2` and script 2 untouched,
per scope.

**One-sentence deliverable: script 1 is trustworthy** — clean on an idle
tenant (both modes), correctly ignores real `accept.sh` traffic instead of
misreading it as loss (the exact build 118 failure, now proven fixed live),
still catches a genuine loss/duplicate/stray inside its own scope, and now
retains a complete diagnostic bundle on every live non-zero run instead of
reporting `status=incomplete` by construction.

Base image digest: `ghcr.io/h-network/base@sha256:10406097c8954af16c62cf0088dea147065146bf4f667c361da96384ed02cbdc`.

## Check 1 — clean is clean, on an idle tenant

Own tenant (`build121a-0824-1610`), no `accept.sh` traffic on it at all.

| mode | result |
|---|---|
| steady (`--count 10 --rounds 2`) | `PACKET_SCOPE ... ignored_out_of_scope=0` — `PACKET_RESULT rc=0 reason=clean` |
| burst (`--count 100 --rounds 2`) | `ignored_out_of_scope=0` — `rc=0 reason=clean`, 220 cumulative bench packets, zero loss/dup |

`ignored_out_of_scope=0` is correct here — the tenant genuinely carried
nothing else.

## Check 2 — ⚠⚠ the one that matters: it survives other traffic

Stood up a real `accept.sh --tenant build121b-0824-1803 --keep` tenant first
(exit `0`, 26/26 plumbing+simulator, all console flows green — the exact
build 118 scenario) and ran the packet harness against that **same**
container, both modes:

| mode | `ignored_out_of_scope` | `PACKET_RESULT` |
|---|---:|---|
| steady | **221** | `rc=0 reason=clean` |
| burst | **221** | `rc=0 reason=clean`, 220 cumulative bench packets, zero loss/dup |

**Both `rc0`, and the ignored count is genuinely non-zero both times** — the
221 records are `accept.sh`'s own real traffic (install, plumbing check,
simulator, console flow-check), the identical shape that produced a false
`rc=3 stray` in `BUILD-118-results.md`. This time it's correctly excluded
from judgment rather than misjudged. The scoping fix is proven against the
exact scenario that found the defect, not a synthetic stand-in for it.

## Check 3 — the gate still fires inside its own scope

**Stray, live, not a fixture** (this also serves check 4 below): injected
one real envelope via `flock.bus.doors.send()` with `destination=bench-1`
and its own `sent` record kept invisible to `docker logs` (no
`/proc/1/fd/1` redirect — the same technique `BUILD-115` used), so the
tenant's real port delivers it and logs a genuine `opened` with no matching
`sent`. Re-ran the harness:
```
PACKET_SCOPE source_or_destination_prefix=bench- ignored_out_of_scope=0
STRAY_OPENED 2f3d17fa81b7465a9b0c1e657c5c1bcc   <- exactly the injected stream_id
PACKET_RESULT rc=3 reason=stray
```

**Loss and duplicate, via `--reconcile-only` fixtures** (built from scratch,
`bench-1` as destination so they're unambiguously in-scope):

| mutation | result |
|---|---|
| `sent`, no `opened` | `PACKET_RESULT rc=1 reason=conservation_failure`, exit 1 |
| `sent` + two `opened` | `PACKET_RESULT rc=2 reason=conservation_failure`, exit 2 |
| `opened` for an unsent `bench-1` stream | `STRAY_OPENED verify121-stray-nosend` / `rc=3 reason=stray`, exit 3 |

Scoping did not remove the gate — all three shapes still fire exactly as
before, this time confirmed with in-scope (`bench-*`) identifiers so there's
no ambiguity about whether the filter itself could have hidden them.

## Check 4 — a non-zero run reports `status=complete`

The live stray run above (check 3) is the first live non-zero run against
current `main`. Its diagnostics:
```
PACKET_DIAGNOSTICS retaining work=/tmp/build121-check4
PACKET_DIAGNOSTICS status=complete files=diagnostic-container.log,diagnostic-inspect.json,diagnostic-processes.txt,diagnostic-keyspace.jsonl,diagnostic-queues.tsv,diagnostic-window.log.jsonl,diagnostic-sha256.txt
```
`diagnostic-queues.tsv` content, confirmed rather than assumed:
```
NO_NONEMPTY_QUEUES: empty lists are deleted after drain
```
**This is the fix that reached `main` thirty minutes before this ticket and
had never run — now it has, live, and it works.** `status=complete`, not
`incomplete`; the marker is present, not an empty file.

## Secret scan, before pushing

Build 116's `Config.Env`-only redaction (`TOKEN|KEY|SECRET|PASSWORD|CRED|
AUTH` by name) confirmed live again in `check3-4-live-stray/diagnostic-
inspect.json` — `API_TOKEN=REDACTED`. Independently swept everything that
denylist does not cover, across **every** file in every check's evidence
(not just the one with diagnostics): the tenant's real token (retrieved
directly from `container/.env`, specifically to know what to search for) —
zero occurrences anywhere; every `diagnostic-keyspace.jsonl` and
`diagnostic-processes.txt` grepped for `token|secret|password|bearer|
authorization` — zero matches; a generic secret-shaped-assignment sweep
across the whole tree — zero matches beyond the harness's own `REDACTED`
line and the healthcheck script's shell variable reference. Clean, checked
before `git add`, not after.

## Out of scope, confirmed untouched

`bus/build-120-script-2` and script 2 — not looked at beyond confirming it
exists as a halted branch; nothing from it used or touched. Nothing wired
into `accept.sh`. Nothing found was fixed (nothing needed fixing — all four
checks passed).

## TEST SIGN-OFF

    claim            script 1 (packet-switching.sh) at main a242393 is trustworthy: clean on an idle tenant, correctly scopes out real accept.sh traffic rather than misjudging it (the exact build 118 defect), still catches loss/duplicate/stray inside its own scope, and retains a complete diagnostic bundle on every live non-zero run (the build 115 defect)
    source sha       a242393 (main)
    artefact         WORKING TREE
    host             lab 172.16.0.14 — correctness only, no rate quoted
    command          container/scenarios/packet-switching.sh --mode steady|burst, both against an idle tenant and against a live accept.sh --keep tenant; --reconcile-only against three from-scratch bench-scoped fixtures
    exit status      check1: 0, 0 (steady, burst). check2: 0, 0 (steady, burst). check3: 1, 2, 3 (loss, dup, stray fixtures) plus 3 (live stray). check4: same live run as check3's stray. All read unpiped

    EXCLUDED         script 2 and bus/build-120-script-2 (halted, untouched); wiring into accept.sh (separate decision); any throughput rate (h-oracle's job)
    population       4 of 4 checks in the spec, all four independently demonstrated live or by from-scratch fixture, none trusted from BUILD-119/120 prose alone

    control          check3: three custody.log mutations (loss, duplicate, stray) built from scratch with bench-1 as destination; one live stray injected via send() with an invisible sent record (destination=bench-1)
    expected locus   PACKET_SCOPE ignored_out_of_scope and PACKET_RESULT lines; PACKET_DIAGNOSTICS status line
    observed locus   same — ignored_out_of_scope=221 both modes in check2 (non-zero, as required); rc=1/2/3 exactly per mutation in check3; status=complete with the NO_NONEMPTY_QUEUES marker in check4
    signature        PACKET_SCOPE ... ignored_out_of_scope=221; PACKET_RESULT rc=0/1/2/3 per check; PACKET_DIAGNOSTICS status=complete files=...; diagnostic-queues.tsv containing NO_NONEMPTY_QUEUES rather than being empty

    evidence         docs/evidence/build-121-a242393/ — accept-tenantB.log, check1-steady/, check1-burst/, check2-steady/, check2-burst/, check3-4-live-stray/, check3-fixtures/{loss,dup,stray}/
                     accept-tenantB.log sha256 78184284f6dab63fda5251a8efa3e622f7e61d1ba9da1332667f002bcc37cb6b
                     check1-steady/custody.log sha256 08ff48c18a9b3454832ad589fa66ce15026e8e2fd8c0440fe06ebe892b79e887
                     check1-burst/custody.log sha256 346ce8c7077d9d270c9f844531ca4a2917f299484eecc7fb5a7878f872b19fba
                     check2-steady/custody.log sha256 09088fbc33950139521c43a1438295132b26e0ec4493b224212ff249699eda0d
                     check2-burst/custody.log sha256 3ceca62afc0018f5297781475cb06678b14a22eaefad0e33f17811a58b1b4765
                     check3-4-live-stray/custody.log sha256 d488353392cee774b2109d39c50d7252bbbe04ee6863822935f475ffec44079a

    verdict          PASS — all four checks confirmed, script 1 is trustworthy on current main
    VERIFIED BY      acceptance — author of the change? NO

    DESTRUCTIVE      identity this run CREATED: tenants build121a-0824-1610 and build121b-0824-1803 (projects h-flock-build121a-0824-1610, h-flock-build121b-0824-1803), own namespaces only
                     what teardown touches: those two projects only, via project-scoped `docker compose down -v`, plus killing the --keep console PID directly
                     protected names refused: none encountered; the four pre-existing hvab-* containers untouched (4/6/8 before and after both tenants)
