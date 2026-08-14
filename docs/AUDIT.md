# Audit — the consolidated list

> ✅ **All 50 rows are closed.** 46 fixed, 4 closed as deliberate or documented.
> Verified on a fresh tenant: 339 tests, plumbing 25/25, simulator 19/19.

Every finding from both independent audits of **`4bc702b`**, merged and ranked.
The raw documents are on the `auditClaude` and `auditCodex` branches; the
comparison of the two offices is in `AUDIT-2026-08-11-comparison.md`.

**How to use this.** Work top down. Each row carries the evidence its auditor
cited, so the first step on any row is to open those lines and decide whether
the finding is real.

| status | means |
|---|---|
| ✅ | checked against the tree by the architect — the finding holds |
| — | **a claim, not yet checked.** A previous auditor on this project cited files that did not exist |
| both | found independently by both offices, which makes it the least deniable |

⚠ **Ranking is by consequence, not by effort.** Several one-line fixes sit near
the top and several large ones near the bottom.

⚠ **A finding is not a mandate.** Some of these describe deliberate choices —
say so on the row and close it, rather than "fixing" something that was decided.

---

## 1. Crashes, data loss and silent wrong behaviour

| # | finding | evidence | source | status |
|---|---|---|---|---|
| 1 | `.append()` called on the `set` that `list_windows` returns — the `__init__` placeholder path raises `AttributeError` | `tmuxhost/host.py:201`, `tmux/ops.py:56` | claude | ✅ **fixed — `set.add`; the path had no test because no case had a stale window with no roster members and no `__init__` yet**
| 2 | `REDIS_PASSWORD` reaches **every agent window** via an exported `REDIS_URL`, never unset — the one thing `API_TOKEN` is unset at line 27 to prevent | `container/entrypoint.sh:108-114`, `:232` | claude | ✅ **fixed — the entrypoint unsets `REDIS_PASSWORD`/`REDISCLI_AUTH`/`REDIS_URL` before tmuxhost; **verified live: an agent pane has none of them****
| 3 | `StopAgent` destroys an api client's **unread mailbox** — `inbox` is classified as identity state, while the docs promise queues are retained | `bus/resources.py:13` | claude | ✅ **fixed — `inbox` moved to data resources, so a retired client's unread mail survives**
| 4 | Retiring `host` deletes the tenant's control endpoint, and the empty roster then turns the switch into a Redis-hammering spin loop — **one chain** | `bus/keys.py:8`, `control/openers.py:16`, `switch/service.py:38-40` | claude | ✅ **fixed — `StopAgent` rejects `api`/`host` before any mutation, and an empty roster sleeps instead of spinning**
| 5 | ~~Two codex agents without profiles share one session directory, so the switch **attributes one agent's activity to the other**~~ **FIXED** — rollouts are now accepted only when the session's first `cwd` is `/workdir/<agent>` | `switch/activity.py:104-120` | claude | ✅ fixed |
| 6 | A Redis interruption can lose an envelope silently: destructive `BLPOP` happens before `popped` is emitted | `switch/service.py:45`, `:48`, `:52-67` | codex | ✅ **resolved as documentation — the blind window is irreducible without a reserve/ack journal; at-most-once kept, the false guarantee removed**
| 7 | The session door never recovers from a broken tmux stream, though the LLD says it does | `session/app.py:135`, `session/control.py:252-253` | claude | ✅ **fixed — the control client reconnects when a command runs after a break**
| 8 | One oversized `%output` line kills the reader permanently | `session/control.py:220`, `:71-76` | claude | ✅ **fixed — 16 MiB line limit on the reader**
| 9 | The session door corrupts non-ASCII terminal output | `session/control.py:193-203`, `session/app.py:159-164` | codex | ✅ **fixed — UTF-8 decode with replacement instead of latin-1**
| 10 | One slow viewer grows the session process without bound | `session/control.py:40-45`, `session/app.py:159-167` | **both** | ✅ **fixed — bounded queue, oldest dropped**
| 11 | The SSE endpoints do blocking Redis I/O on the event loop | `api/app.py:516`, `:659`, `:443` | claude | ✅ **fixed — the blocking read runs in a thread**
| 12 | One malformed roster row makes `/board` return `404` for the **entire tenant** | `api/app.py:705-712`, `bus/roster.py:6-8` | claude | ✅ **fixed — a malformed roster row is skipped, not fatal for the tenant**
| 13 | The pane→agent map assumes one pane per window and nothing enforces it; duplicate window names silently merge two terminals | `session/control.py:128-139`, `:185-203` | **both** | ✅ **fixed — the first pane wins for a duplicated window name**
| 14 | The activity tailer restarts from byte 0 when the newest session file changes, replaying a whole file into a capped stream | `switch/activity.py` | claude | ✅ **fixed — offsets are kept per path and migrate from the old shape**
| 15 | One undecodable byte in the window-log spool makes the tailer re-emit forever, never advancing or truncating, with no log record | `switch/windowlog.py` | claude | ✅ **fixed — an undecodable line is skipped past, with `window_log_decode_error` recorded**
| 16 | ~~An port that cannot get the busy tag spins forever~~ **REJECTED — deliberate.** Non-expiry and non-takeover are stated choices (`LLD-bus-and-switch.md:546-568`, `CONTRACTS.md:316-330`), with `HGETALL delivering` and ingress depth exposed for diagnosis | `port/runner.py:163-168` | claude | ✅ closed |

## 2. A failure that reads as success

| # | finding | evidence | source | status |
|---|---|---|---|---|
| 17 | `paste_text` discards every tmux return code, so a failed paste is reported as a successful open — and `LLD-port-tmux` sells that as the design's justification | `tmux/ops.py:364-378`, `port/openers.py:68-82` | **both** | ✅ **fixed — `paste_text` raises `TmuxCommandError` and cleans the buffer; a failed paste is no longer a successful open**
| 18 | `list_windows` cannot distinguish "tmux failed" from "no windows" | `tmux/ops.py:56-60` | claude | ✅ **fixed — a non-zero tmux raises; a genuinely empty session still returns an empty set**
| 19 | Malformed WebSocket input kills the connection instead of producing an error frame | `session/app.py:168`, `:220` | claude | ✅ **fixed — a bad frame gets `{"error": …}` and the connection survives**
| 20 | An SSE stream that fails mid-flight cannot return its status code | `api/app.py:446`, `:490-492` | claude | ✅ **fixed — a mid-flight SSE failure emits an `event: error` frame before closing**
| 21 | A Redis failure during a stream read is reported as `422`, and `API.md` tells clients not to retry `422` | `api/app.py:444-447`, `docs/API.md:677` | claude | ✅ **fixed — infrastructure failure is `500`, not `422`; clients are told to retry**
| 22 | Malformed `as` values can produce 5xx despite the documented 422 contract | `api/app.py:600-617`, `bus/roster.py:15-19` | codex | ✅ **fixed — non-string `as` rejected before it reaches Redis. ⚠ **The first test passed against unfixed code**: its fake returned `None` where redis-py raises `DataError`**

## 3. The hire path is second class

✅ **Closed by deleting the second implementation.** Rows 23–25 were one defect
three times: `StartAgent` created windows synchronously while `tmuxhost` created
them from the roster, and the two drifted every time either changed. The
synchronous creator is gone — `StartAgent` publishes desired state and
`tmuxhost` is the only thing that builds a window.

| # | finding | evidence | source | status |
|---|---|---|---|---|
| 23 | A hired agent's guide names no lead, and its trust is seeded into the wrong account | `tmux/ops.py:311-319`, `control/runner.py:70-76` | claude | ✅ **fixed by deletion — trust now goes to the profile's own account. ⚠ **The simulator's case 4 had been passing because of this bug****
| 24 | Hiring an existing name cannot apply changed launch configuration | `control/openers.py:43-69`, `tmux/ops.py:337-348` | codex | ✅ **fixed by deletion — `StartAgent` publishes desired state, kills a stale window, and `tmuxhost` recreates it**
| 25 | A third window-creation path still ignores `endpoint` | `tmuxhost/host.py:167-170`, `control/runner.py:56-68` | claude | ✅ **fixed by deletion — one window-creation path remains, so there is nothing left to drift**
| 26 | A departed agent's egress is never drained, so re-hiring the name delivers it | `switch/service.py` | claude | ✅ ****REJECTED — deliberate.** `egress` is classified as data, so a re-enrolled name resumes its ingress, egress, inbox and board. Name continuity is the decision; nothing is drained. Recorded in `LLD-bus-and-switch`**

## 4. The watchdog

| # | finding | evidence | source | status |
|---|---|---|---|---|
| 27 | The credential check has no idea what an endpoint agent is — a local-model agent needs no vendor login and is reported as missing one | `watchdog/service.py:208-228` | claude | ✅ **fixed — endpoint agents are excluded from vendor credential checks, and stale `credential.alerted` clears. ⚠ Live: this office runs agents on vLLM and ollama**
| 28 | A stalled agent whose window is gone is never reported | `watchdog/service.py:171-173`, `:90-91` | claude | ✅ **fixed — a missing window now reports `window_missing: true` instead of being read as no signal. `HLD` corrected: an agent that cannot be observed is not an agent that is fine**
| 29 | One failing maintenance job silently disables the other four, and the log record names only the exception class | `watchdog/service.py` | claude | ✅ **fixed — window lookup, stalls, blocked verdicts and credentials have independent failure boundaries, and the record carries `type: message`**

## 5. Documented claims that are false

**The error vocabulary is now stated in `API.md` §7** — client fault is `422`/`404`
and must not be retried, infrastructure fault is `500`/`503` and must be, an SSE
stream that fails mid-flight emits an error event because its headers are already
sent, and a malformed WebSocket frame gets an error frame rather than a closed
socket.

⚠ **These cost the most trust per byte.** A doc that is wrong is worse than one
that is missing, because it is acted on.

| # | finding | evidence | source | status |
|---|---|---|---|---|
| 30 | The broadcast fan-out **is** atomic — `pipeline()` defaults to `transaction=True` — while the LLD says "pipelined, not atomic" | `switch/service.py:78`, `LLD-bus-and-switch.md:637` | codex | ✅ **fixed as documentation — atomic fan-out **kept** as the stronger property; the LLD now says transactional pipeline**
| 31 | `CONTRACTS` §3 says nothing writes a log file. Something does, and the switch depends on it. The rest of §3 is stale too | `bus/logging.py:75-85`, `switch/windowlog.py:25-45` | **both** | ✅ **fixed — `CONTRACTS` §3 corrected; the window-log spool exists and the switch depends on it**
| 32 | The five-record claim does not hold for `recipient: "all"` — per-recipient deliveries are indistinguishable in the log | `bus/doors.py:53` | claude | ✅ **fixed — the five-record claim is now scoped to unicast; a broadcast leaves 3 + 2 per recipient**
| 33 | `API.md` tells browser developers to open the WebSocket with a Bearer header. Browsers cannot send one | `docs/API.md:625-642`, `session/app.py:88-96` | **both** | ✅ **fixed — browsers may pass `?token=`, with `access_log=False` so it never reaches the tenant log, the cost stated, and the server-side proxy recommended**
| 34 | The WebSocket close-code vocabulary is undocumented and `4401` never reaches a client | `session/app.py:180-219` | claude | ✅ **fixed — close codes documented (1000 / 4401 / 1011)**
| 35 | `/alerts` names a field the watchdog never writes; only a fallback saves it | `api/app.py:751`, `watchdog/service.py:103-107` | claude | ✅ **fixed — `/alerts` reads the field the watchdog actually writes, not a fallback**
| 36 | `LLD-port-tmux` §4 documents a pane read that does not exist and would break invariant 7 | `LLD-port-tmux.md:189-192` | claude | ✅ **fixed — the pane read that does not exist is gone; the LLD describes file-only verification**
| 37 | `LLD-tmux-host` describes two bugs that were already removed | `tmuxhost/host.py:185-208`, `tmux/ops.py:136-142` | codex | ✅ **fixed — the two removed bugs no longer described as present**
| 38 | "The switch does not rewrite the envelope" is absolute in one place and contradicted by a documented exception elsewhere | `LLD-bus-and-switch.md:632-635`, `:743-747` | codex | ✅ **fixed — the no-rewrite claim now names port stamping as the exception**
| 39 | `popped` is not emitted "before doing anything" and carries the corrected producer | `switch/service.py:52-67` | **both** | ✅ **fixed — `popped` follows pop, parse and stamping, and the LLD says so**
| 40 | The wire encoding of terminal bytes is documented only in a comment in the reference client | `session/control.py:197`, `LLD-session.md:176` | claude | ✅ **fixed — the wire encoding is in `API.md` and `LLD-session`, not only a client comment**
| 41 | An example response omits the `vab` field that is implemented and advertised | `api/app.py:584-598`, `docs/API.md:220-223` | codex | ✅ **fixed — the example carries `vab`**
| 42 | `CONTRACTS` §9 omits several variables the container sets and modules read | `docs/CONTRACTS.md` | claude | ✅ **fixed — `CONTRACTS` §9 lists the variables the container sets**
| 43 | Two smaller doc claims that are false today | `LLD-tmux-host.md:156`, `docs/TODO.md:54` | claude | ✅ **fixed — both claims corrected; the `TODO` line was flagged, not edited, and I corrected it**

## 6. Fragility, cost and hygiene

| # | finding | evidence | source | status |
|---|---|---|---|---|
| 44 | `Redis.from_url` yields **zero** connection retries — load-bearing, undocumented, and the obvious "improvement" would break at-most-once | `bus/` | claude | ✅ **documented, not changed — zero retries is what makes at-most-once true: retrying a destructive `BLPOP` whose reply was lost would remove a second envelope**
| 45 | Nothing bounds the size of anything a client can send or ask for | `api/app.py:600-639`, `bus/doors.py:28` | claude | ✅ **fixed — 1 MiB payload limit, stated in `API.md` §7 and rejected with the agreed vocabulary**
| 46 | The Redis readiness wait has no deadline | `container/entrypoint.sh:128` | claude | ✅ **fixed — `REDIS_READY_SECONDS` (default 30) bounds the wait, then it exits**
| 47 | A configured Redis password is not URL-encoded, so reserved characters produce a broken `REDIS_URL` | `container/entrypoint.sh:107-113` | codex | ✅ **fixed — the password is percent-encoded into the infrastructure URL**
| 48 | Presence pulls up to 1000 stream entries per agent per pass to read one timestamp | `bus/` | claude | ✅ **fixed — presence reads 10 entries, not 1000**
| 49 | `waited` reports the configured threshold, not how long the switch actually waited | `switch/service.py` | claude | ✅ **fixed — `waited` reports measured elapsed time, including scheduler delay**
| 50 | Dead code that hides an intent | — | claude | ✅ **fixed by deletion — the unreachable branch is gone and a test pins that `all` is rejected as both agent and resource**

---

## What the auditors read and found correct

Both offices were told that "I found nothing wrong" is a valid finding, and both
used it. Between them they signed off the envelope contract, the roster as a MAC
table, the at-most-once delivery path, the token enforcement on both doors, the
port's kick-and-exit lifecycle, and the board's pull-based transitions.

⚠ **`entrypoint.sh:107-114` is the row to remember.** Two offices found **two
different defects in the same four lines**, and neither found the other's. That
is the argument for more than one model, in one line of a table.
