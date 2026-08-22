# Build 81 — delivery verification unit result

## Result

The unit arm implements the proposed heuristic but does not establish its live
false-negative rate. `DeliveryVerifier` now treats later `input`, `output`, or
`tool` activity as progress, defaults its direct verification window to 120
seconds, and bounds each activity-stream read at the earliest eligible marker's
millisecond. Event timestamps remain the ordering authority after that bounded
read.

The intentional trade is a false positive: output or tool activity from a turn
that began before the paste can clear a marker without proving that paste was
consumed. That is preferable to declaring 30–92% of observed healthy deliveries
unverified. A wedged process or login prompt produces none of the three activity
kinds. The no-retry rule and the `blocked` hash shape are unchanged.

The environment fallback used by `watchdog/service.py` is owned by bus in Build
80. The exact requested integration edit is
`os.environ.get("VERIFY_AFTER_SECONDS", "10")` to
`os.environ.get("VERIFY_AFTER_SECONDS", "120")`; it is deliberately absent from
this branch to avoid overlapping that file.

## Verification

- `python3 -m pytest -q` exited 0 unpiped: 404 passed and 5 subtests passed.
- `python3 tools/check_citations.py` exited 0 unpiped: 0 hard failures and 47
  near misses.
- The live four-agent Nemotron rate is excluded and remains for architect.

```
TEST SIGN-OFF

  claim            the unit evidence reader accepts post-marker output/tool activity, rejects absent or pre-marker activity, and bounds its Redis read
  source sha       b8e9954032294360caffde5166b44b2f6558d673
  artefact         COMMIT
  host             NOT MATERIAL — hermetic in-memory Redis double and fixed timestamps
  command          python3 -m pytest -q
  exit status      0 — read UNPIPED

  EXCLUDED         live tmux paste, real CLI activity files, Redis, watchdog scheduling, four-agent Nemotron traffic, and the measured false-negative rate
  population       13 DeliveryVerifier contract tests within 404 repository tests; required five-case unit arm covered 5 of 5

  control          monkeypatch VERIFICATION_ACTIVITY_KINDS from input/output/tool back to input-only for the output-only case
  expected locus   DeliveryVerifier._input_times omits the post-marker output timestamp; poll emits delivery_unverified
  observed locus   same
  signature        _input_times returned []; emitted event was delivery_unverified

  evidence         tests/test_verification.py at b8e9954032294360caffde5166b44b2f6558d673

  verdict          SMOKE
  VERIFIED BY      api — author of the change? NO
```

---

## Live arm — architect, 2026-08-22

```
TEST SIGN-OFF

  claim            widening verification evidence to input/output/tool removes the
                   false-negative flags seen on real local-model agents
  source sha       2f9fc10 + 321737a (Dockerfile shadowing fix)
  artefact         COMMIT
  host             h-oracle 172.16.0.11 — 3 agents on nemotron-lightning via vLLM
  command          CONTAINER=h-flock-b81-tenant-1 POD=acme TENANT=b81 \
                     AGENTS="b81-a b81-b b81-c" ROUNDS=10 \
                     bash container/scenarios/tmux-nemotron.sh /tmp/b81-capture
                   python3 container/scenarios/analyse-verification.py custody.jsonl
  exit status      0   read unpiped

  EXCLUDED         the lab host, api-door delivery, broadcast, any run longer than
                   ~10 min, and an ORGANICALLY wedged agent — see the control note
  population       40 deliveries opened, 3 agents, 10 rounds each

  control          a pending.verify marker aged past the 120 s window and timestamped
                   AFTER the agent's newest activity (14:48:00 vs newest 14:46:50)
  expected locus   the watchdog's DeliveryVerifier, as delivery_unverified + a
                   blocked alert naming the stream
  observed locus   same
  signature        {"kind":"blocked","agent":"b81-c","stream_id":
                   "CONTROL-AFTER-LAST-ACTIVITY","unconsumed_s":359,"writer":"watchdog"}

  evidence         /tmp/b81-custody.jsonl on h-oracle — ⚠ TORN DOWN, no sha256
  verdict          PASS
  VERIFIED BY      architect — author of the change? NO (tmux wrote it), but see below
```

### The number

| run | flagged | of | rate |
|---|---|---|---|
| build 74, before | 4 | 13 | **31%** |
| build 81, after | **0** | **40** | **0%** |

### ⚠ Four things that qualify this

**1. The control is synthetic.** I could not produce an organically wedged agent:
`tmux kill-window` is healed by `tmuxhost` within seconds, and `office pause`
left the pane responsive. So the control injects a marker rather than breaking an
agent. It exercises `DeliveryVerifier`'s judgement exactly; it does **not**
exercise the paste path into a dead pane.

**2. Three of my controls were invalid before this one worked** — killing a window
(healed), pausing without `AGENT_NAME` (the command errored and I read the `0` as
a result), and an aged marker placed 63 s *before* the agent's newest activity, which
verified correctly and looked like the check was dead. **Each failed at the wrong
locus, and each initially read as a clean result.**

**3. `0 of 40` is also what a dead check looks like.** Ruled out directly: a marker
appears in `pending.verify` within seconds of a send, and is gone after a poll —
so markers are created and judged. The mechanism was proven alive before the rate
was believed.

**4. I signed my own live arm.** `author? NO` is true of the code but I wrote the
harness and the analyser, so this is not fully independent.
