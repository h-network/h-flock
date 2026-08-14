# Two audits of `4bc702b`, side by side

Two offices of three agents, same commit, same brief, no remote, no ssh key.
Neither saw the other's work: the codex office was briefed directly rather than
through the office that had already finished.

| | claude | codex |
|---|---|---|
| findings | ~35 | 14 |
| written | 118,973 bytes | 22,542 bytes |
| commits | 4, including a cross-check that merged two findings into one chain | 1 |
| where the auditors wrote | own clones, lead collected | **straight into the lead's clone** — `/workdir` is shared and every agent is the same user |
| branch | `auditClaude` | `auditCodex` |

⚠ **Volume is not quality.** codex wrote a fifth as much and found things claude
missed. What follows is what each said, not who wrote more.

## Where they agree — corroborated, and therefore the least deniable

| area | claude | codex |
|---|---|---|
| **a tmux failure reads as success** | `list_windows` cannot distinguish "tmux failed" from "no windows" (#7); `paste_text` discards every return code while the LLD sells that as the design's justification (#6) | "a tmux command failure is reported as a successful open" (#1) |
| **the logging contract** | `CONTRACTS` §3 claims nothing writes a log file — something does, and the switch depends on it (F7); the five-record claim does not hold for broadcast (F5); `popped` is not emitted "before doing anything" (F13) | "the logging contract contradicts both the implementation and itself" (#3); `popped` comes after a destructive `BLPOP`, leaving windows where an envelope is gone and unrecorded (#1) |
| **an unbounded session viewer** | one slow viewer grows the session process without bound (B13) | "every slow session viewer is an unbounded memory sink" (#3) |
| **the WebSocket auth contract** | `API.md` tells browser developers to send a Bearer header they cannot send (B10); `4401` never reaches a client (B11) | "the public authentication contract conflates HTTP and WebSocket failures" (#4) |
| **window / pane identity** | the pane→agent map assumes one pane per window and nothing enforces it (A6) | duplicate window names silently merge two terminals (#2) |
| **the hire path is second class** | a hired agent's guide names no lead and its trust is seeded into the wrong account (#2) | hiring an existing name cannot apply changed launch configuration (#2) |
| **`entrypoint.sh:112`** | the Redis password reaches every agent window — the thing `API_TOKEN` is unset at line 27 to prevent (#3) | the password is not URL-encoded, so a password with reserved characters produces a broken `REDIS_URL` (#4) |

The last row is the sharpest illustration: **the same line, two unrelated
defects**, neither auditor finding the other's.

## Only claude found

Crashes and data loss, mostly on paths that run rarely:

- `host.py:201` calls `.append()` on the `set` that `ops.py:56` returns — the
  `__init__` placeholder path raises `AttributeError`. ✅ **verified**
- `StopAgent` destroys an api client's unread mailbox; the docs promise
  retention (F6)
- retiring `host` deletes the tenant's control provider, and an empty roster
  then spins the switch against Redis — one chain, found by cross-checking two
  separate findings (F2+F3)
- two codex agents without profiles share a session directory, so the switch
  **attributes one agent's activity to the other** (F1)
- the activity tailer restarts from byte 0 when the newest session file changes,
  replaying a whole file into a capped stream (F10)
- the session door never recovers from a broken tmux stream, though the LLD says
  it does (A1); the SSE providers do blocking Redis I/O on the event loop (A3)
- one malformed roster row makes `/board` return `404` for the whole tenant (B14)
- nothing bounds the size of anything a client can send or ask for (B8)
- `Redis.from_url` yields zero connection retries — load-bearing, undocumented,
  and the obvious "improvement" would break at-most-once (F4)

## Only codex found

Fewer, and each one a claim in a document that is precisely wrong:

- **the broadcast fan-out is atomic.** `service.py:78` calls `pipeline()` with no
  arguments and redis-py defaults `transaction=True`, so it is `MULTI`/`EXEC`.
  `LLD-bus-and-switch.md:637` says "pipelined, not atomic". ✅ **verified**
- `LLD-tmux-host` documents two bugs that were already removed
- "the switch does not rewrite the envelope" is stated absolutely in one place
  and contradicted by a documented exception elsewhere
- the session door corrupts non-ASCII terminal output
- malformed `as` values produce 5xx despite the documented 422 contract
- an example response omits the `port_type` field that is implemented and advertised

## What this says about the exercise

- **Both offices used the product correctly without being told how.** Tickets
  through `todo → doing → done`, findings by `office send`, the lead collecting.
  Nobody scripted that.
- **The two models fail differently.** claude went wide and found runtime
  defects; codex went narrow and found false claims. Reading a default argument
  value — `transaction=True` — is not the same skill as tracing a placeholder
  path to an `AttributeError`, and neither office did both.
- ⚠ **Three findings are verified; the rest are claims.** A previous auditor on
  this project cited files that did not exist. Every finding acted on gets
  checked against the tree first.
- ⚠ **The audits are a snapshot of `4bc702b`.** Anything changed since is not in
  what they reviewed.

The raw documents are on the `auditClaude` and `auditCodex` branches, three files
each, local until someone decides they belong on the remote.
