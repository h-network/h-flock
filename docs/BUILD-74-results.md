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

## Rerun — host-reachable model address

The fresh `nemotron74r` tenant used `http://172.17.0.1:8000` as Claude's
provider base. Before prompts were sent, two requests from inside the tenant
proved that `/v1/models` served `nemotron-lightning` and that a real
`/v1/messages` request returned a message. All three participants then declared
completion within the first polling interval with `ROUNDS=3`.

### Count refusal and exact workload set

The instruction asked for nine sends, but the agents produced 13. Therefore the
first `analyse-run.py --expect 9 --source-prefix b74-` invocation exited 1: it
saw 14 paths after the deliberately misclaimed-source frame was stamped to
`b74-a`, and correctly refused a log containing more traffic than declared.
This was not rerun with a convenient expected value.

The captured AOF makes the provenance separable without guessing: a
model-originated frame is an egress frame whose header source equals the owner
of its `b74-*` egress queue. That gives 13 model frames (4 from `b74-a`, 6 from
`b74-b`, and 3 from `b74-c`). The synthetic source-stamp control has claimed
source `misclaimed` and is excluded. Joined back to the already captured
custody log, the exact model set is:

| model-originated stage | coverage |
|---|---:|
| sent | 13 / 13 |
| popped | 13 / 13 |
| forwarded | 13 / 13 |
| kick_started | 13 / 13 |
| received | 13 / 13 |
| opened | 13 / 13 |

There were zero duplicate `(stream_id, recipient)` openings, zero losses, zero
dead letters, and no incomplete custody paths. `received -> opened` p50 was
507 ms. Four of 13 deliveries were `delivery_unverified` (30.8%), all four to
`b74-c`; zero were `delivery_unjudged`.

The extra traffic is observable model behaviour, not a stale tenant. Besides
the requested messages, the agents duplicated a numbered code-fence message
and sent acknowledgements after peer input. One attempted message became the
valid but surprising exact body bytes
`{"kind":"Message",...,"payload":{"text":""}}`. The empty payload traversed
all custody stages and opened; it did not break the frame or port, but it is a
counterexample to treating “one send command” as “one non-empty natural
message.”

### v4 integrity and cleanup

The AOF comparison covered all 17 forwarded frames: three API instructions,
13 model-originated messages, and the source-stamp control. It found zero
missing ingress frames, body mismatches, ttl/hops mismatches, source mismatches,
or parse failures. The source-stamp control was present and passed:
`claimed=misclaimed`, `stamped=b74-a`, `body_identical=true`. Newlines, code
fences, quotes, backslashes, Unicode, JSON-inside-JSON, and the empty string all
arrived byte-identically. No payload broke the v4 fabric.

Logs and AOF were captured before any analysis or pane inspection. The rerun
evidence and checksums are retained at
`/home/halil/tmux-build74/evidence-rerun/`. The scoped
`h-flock-nemotron74r` project was removed with `down -v`; `h-flock-office`
remained running with the same identity and start time. No performance or
throughput figure was calculated or reported.
