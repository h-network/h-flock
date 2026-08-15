# Build 74 — real tmux/Nemotron integration result

## Result: refused before the model workload

The first run did not produce the intended 30 agent-originated envelopes. All
three real Claude windows received and opened their instruction, then each
reported `API Error: Unable to connect to API (ConnectionRefused)`. The tenant
had `ANTHROPIC_BASE_URL=http://127.0.0.1:8000`; from inside the tenant that is
the tenant itself, not the Nemotron server on the h-oracle host.

The participant-declared completion gate expired after its 1,800-second
wall-clock deadline with `participants_done=0/3`. There was no retry, prompt
reinjection, or configuration change. This is the required first-run finding:
`analyse-run.py --expect 30 --source-prefix b74-` exited 1 and refused every
stage rather than presenting partial measurements.

| agent workload stage | coverage |
|---|---:|
| sent | 0 / 30 (REFUSED) |
| popped | 0 / 30 (REFUSED) |
| forwarded | 0 / 30 (REFUSED) |
| kick_started | 0 / 30 (REFUSED) |
| received | 0 / 30 (REFUSED) |
| opened | 0 / 30 (REFUSED) |

Consequently, duplicate count, loss attribution, model-payload byte identity,
model-workload `received -> opened` p50, and model-workload verification rates
are unavailable. No model-generated payload reached the wire, so there is no
payload counterexample to report.

## What the independent prompt controls proved

The three API-to-window instruction envelopes covered all six custody stages
3/3, with zero duplicate `opened` records. Their `received -> opened` p50 was
506 ms. They produced zero `delivery_unverified` and zero
`delivery_unjudged` records (0/3 for each). These are control-path results, not
substitutes for the refused model workload.

The captured Redis AOF contained those three egress/ingress pairs. All three
had byte-identical bodies, ttl decremented once, hops incremented once, and
their source stamped to their actual egress owner. There were zero missing
ingress frames, body mismatches, counter mismatches, source mismatches, or AOF
parse failures.

The deliberately misclaimed-source control did not execute: its `docker exec`
heredoc omitted stdin attachment, so Python received an empty program and
exited zero. The harness now uses `docker exec -i`, and the AOF analyser now
refuses a capture with no source-stamp control. It also prints the exact sent
and arrived body bytes for any future mismatch. The control was not rerun after
the integration refusal.

## Method and cleanup

- Host: h-oracle, using the integration-only exception in the build spec.
- Fresh compose project: `h-flock-nemotron74`; tenant: `nemotron74`; agents:
  `b74-a`, `b74-b`, and `b74-c`, all real tmux Claude windows configured for
  `nemotron-lightning`.
- Custody logs were not read during the run. Docker logs and the Redis AOF were
  captured first; analysis and pane capture happened only after the bounded
  run and capture phase ended.
- Evidence, including custody log, AOF, three pane captures, summaries, and
  checksums, is retained on h-oracle at
  `/home/halil/tmux-build74/evidence/`.
- The scoped compose project was removed with `down -v`. `h-flock-office` was
  untouched and remained running with the same container identity and start
  time.
- No performance or throughput figure was calculated or reported.

Local verification after the harness changes: 388 tests and 5 subtests passed.
