# BUILD 118 results — an acceptance round with the packet harness in it

**Base: `main` at `95bf312`.** Host: the lab, correctness only — no rate
quoted. This is a run, not a change; nothing was modified.

## Both verdicts, reported separately, not combined

| step | command | result |
|---|---|---|
| 1 — `accept.sh` | `bash container/accept.sh --tenant build118-0824-1647 --keep` | **`EXIT:0`** — 26/26 plumbing+simulator, all console flows green |
| 2a — packet harness, steady | `packet-switching.sh --mode steady --count 10 --rounds 2` | **`rc=3 reason=stray`** |
| 2b — packet harness, burst | `packet-switching.sh --mode burst --count 100 --rounds 2` (the `BUILD-117` recipe) | **`rc=3 reason=stray`** — same cause as 2a |

Base image digest: `ghcr.io/h-network/base@sha256:10406097c8954af16c62cf0088dea147065146bf4f667c361da96384ed02cbdc`.

## What the packet harness's `rc=3` actually is — the new-combination finding

⚠ **Both runs were against the SAME container that `accept.sh --keep` had
already produced real fabric traffic on** — install, plumbing check
(architect↔sme-2 messages, telegram round-trips), the failure simulator, and
console flow-check hires/retires. `judge()` in `packet-switching.sh` reads
the **entire** `docker logs` history with no filter for its own `bench-*`
participants, so that real traffic and the harness's own packets are judged
together.

Traced all four "stray" stream IDs in the steady run: every one is
`source=architect`, `destination` is `sme-2` (×2) or `telegram` (×2) —
plumbing-check's own real agent-to-agent messages, not harness packets.
Each has real `popped`/`forwarded`/`kick_started`/`received`/`opened`
records but **no `sent` record ever reaches `docker logs`**, because
`office send` issued from inside a tmux pane emits its `sent` line to the
`docker exec` session's own stdout, not to PID 1's — the same exec-vs-logs
boundary `BUILD-CONVENTION` already documents, here triggering a false
`stray` rather than a missing log line.

**The harness's own `bench-*` packet accounting was fully clean in both
runs**, checked separately from the noise: 20 sent in steady, 220
cumulative by the end of burst (20 + 200), **zero with no matching
`opened`, zero with more than one** — no loss, no duplicate, among any
`bench-*` packet, in either run. The burst run's own known 5-envelope loss
did **not** reproduce this time (consistent with `BUILD-114-results.md`
calling it cardinality/timing-sensitive, not universal).

**So the `rc=3` on both runs is real and correctly detected — the harness
did exactly what it's specified to do — but its cause has nothing to do with
packet switching under load.** It is a structural property of running the
harness, unmodified, against a container that already carries real
pane-driven agent traffic: **any** legitimate `office send` from inside a
pane will read as a stray to `judge()`'s unfiltered ledger. This is the
"new combination finds new things" result the ticket asked for.

## The deliverable sentence — what a combined gate would have returned

**A naive combined gate (both must return 0) would have reported this ENTIRE
round as FAILED**, on both the steady and burst passes, despite `accept.sh`
being fully clean and the harness's own packet-switching accounting also
being fully clean — the failure would be entirely an artifact of judging
unrelated real traffic, not a genuine defect in anything under test that
round. **A `100` from the harness would need its own third bucket**, not
folded into either pass or fail — matching `accept.sh`'s own `0`/`1+`/`100`
distinction, since `100` here means "did not drain," which per
`packet-switching.sh:143` also means diagnostics never captured at all (see
`BUILD-115-results.md`). **A `5` (`INDETERMINATE_FORWARD`) would need the
same treatment** — `BUILD-114-packet-switching-harness.md` itself says
collapsing an indeterminate forward into pass or fail is exactly the defect
build 92 was refused for, and a combined gate that maps `5` to either would
reintroduce it one layer up. None of this is a wiring decision made here —
it's the input the wiring decision needs, per the ticket.

## Build 116's token path — did this round exercise it?

**No.** Grepped `container/accept.sh`, `container/plumbing-check.sh`, and
`container/sim-blocked.sh` for the three `api-*.sh` scenario names build 116
changed (`api-auth-and-limits.sh`, `api-concurrency-and-time.sh`,
`api-session-and-log-privacy.sh`): zero matches in any of them.
`accept.sh`'s own flow never reaches those scripts, so build 116's new
token-acquisition path was **not** exercised by this round, live or
otherwise.

## Secret scan, before pushing

⚠ **This harness captured a live token once already (`BUILD-115`).** Build
116 added redaction to `packet-switching.sh`'s own `diagnostic-inspect.json`
capture (env vars matching `TOKEN|KEY|SECRET|PASSWORD|CRED|AUTH` by name) —
confirmed live: this round's `diagnostic-inspect.json` correctly shows
`API_TOKEN=REDACTED` in both bundles. ⚠ **That denylist only covers
`Config.Env`.** Independently swept everything it does *not* cover before
staging anything:

- The tenant's real token (`3811022881d6b722b5c28c764ce28720`, confirmed via
  a direct `docker inspect` on the live container, bypassing the harness's
  redaction, to know what to search for): **zero occurrences anywhere in
  either evidence bundle.**
- `diagnostic-keyspace.jsonl` (raw Redis value dump) and
  `diagnostic-processes.txt` (`ps -ef`, carries argv) in both bundles:
  grepped for `token|secret|password|auth|bearer`, case-insensitive: **zero
  matches.**
- A generic secret-shaped-assignment sweep (`(token|secret|password|
  api_key|bearer)[=:]\S{16,}`) across every file in both bundles, excluding
  the harness's own `REDACTED` lines and the healthcheck script's shell
  variable references: **zero matches.**

Clean. Pushed as evidence below.

## Out of scope, confirmed not touched

`accept.sh` and `packet-switching.sh` — not modified. Not wired together —
still two separate invocations, two separate exit codes. Nothing found was
fixed.

## TEST SIGN-OFF

    claim            a real accept.sh --keep tenant and the packet harness (both modes) can run in the same round without either crashing the other, and their two verdicts, kept separate, expose a real interaction (unfiltered ledger + pane-driven office send = false stray) that neither tool finds alone
    source sha       95bf312 (main), own tenant and project
    artefact         WORKING TREE
    host             lab 172.16.0.14 — correctness only, no rate quoted
    command          container/accept.sh --tenant build118-0824-1647 --keep; container/scenarios/packet-switching.sh --mode steady --count 10 --rounds 2; --mode burst --count 100 --rounds 2 — all three against the same CONTAINER/TENANT
    exit status      accept.sh: 0 (unpiped). packet-switching.sh steady: 3. packet-switching.sh burst: 3. Both read unpiped, reported separately, never combined

    EXCLUDED         wiring accept.sh to packet-switching.sh (a separate decision); any throughput number (h-oracle's job); build 116's api-* token path (accept.sh does not reach it, confirmed by grep)
    population       one round, both harness modes, against one shared live tenant

    control          none injected — this is an observational run, not a fault-injection one. The rc=3 cause was traced by inspecting the custody log's own source/destination fields on the four stray stream IDs, not by mutating anything
    expected locus   PACKET_RESULT line and exit code from each packet-switching.sh invocation
    observed locus   same — rc=3 reason=stray, both modes, same four pre-existing stream IDs each time (custody.log accumulates across invocations against the same container)
    signature        STRAY_OPENED <sid>, source=architect destined to sme-2/telegram, no matching sent record in docker logs

    evidence         docs/evidence/build-118-95bf312/accept.log sha256 ec906d1970a8c3a3fe80e8f5034aa5ce9b27ffdd2dd9bea82c07d3ea70dd9591
                     docs/evidence/build-118-95bf312/packet-steady/custody.log sha256 71c57be27155f2bca13a32f3fd26b93f825038e00e04d838b1659c8b1143a996
                     docs/evidence/build-118-95bf312/packet-burst/custody.log sha256 c7b7fdb471b60adf84a9456392805620a2563d288bfbaff5dc615f1e3889850c
                     full diagnostic bundles for both packet-switching.sh invocations retained in the same directory, scanned for secrets before push (see above)

    verdict          PASS on both individual verdicts (accept.sh clean; harness's own packet accounting clean); the combined-gate question is answered as a sentence per the ticket, not decided
    VERIFIED BY      acceptance — author of the change? NO (this build changes nothing; there is nothing to be the author of)

    DESTRUCTIVE      identity this run CREATED: tenant build118-0824-1647 (project h-flock-build118-0824-1647), own namespace only
                     what teardown touches: that project only, via `docker compose -p h-flock-build118-0824-1647 down -v`, plus killing the --keep console PID directly
                     protected names refused: none encountered; the four pre-existing hvab-* containers untouched (4/6/8 before and after)
