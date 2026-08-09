# Build 18 — the activity feed

> What an agent is *doing*, as data. An app renders it as a typing indicator or
> a running commentary; `verify` and the watchdog read the same feed later.
>
> **Base on `main`.** Branch `<lane>/build-18-activity`, push to origin.

---

## 1. The idea, and why it is cheap

**The CLIs already write a structured activity log — we do not have to derive
one.** Measured on a real claude session file:

```
record types: user, assistant, system, attachment, …
tool calls  : Bash 901, Write 54, Edit 51, Read 20, Grep 1
```

That is a JSONL the CLI appends to as it works. Tailing it gives "is it working"
and "what is it doing" with **no screen parsing at all**.

⚠ **This is what keeps invariant 7 intact.** *Nothing reads a terminal to make a
decision* — and nothing here does. A session file is the CLI's own data format,
not its rendering. Do not fall back to `capture-pane` for any part of this; if a
CLI has no file, it has no feed (§5).

## 2. Producer, not policy

```
  CLI session JSONL  ──tailed by the router──►  activity stream per agent
                                                    │        │        │
                                              /activity   verify   watchdog
                                               (an app)   (later)   (later)
```

**Activity is facts. The watchdog is judgement.** Thresholds, who gets alerted,
what counts as stalled — none of that belongs here. Build 18 emits events and
stops.

⚠ **Nothing in this build consumes the feed except the api route.** `verify` and
the watchdog are separate builds and must not be anticipated with hooks,
callbacks or config they might one day want.

---

# A. The tailer — `bus`

## A1. Where the files are

| CLI | path | |
|---|---|---|
| claude | `<config-dir>/projects/<slug of cwd>/<session>.jsonl` | config dir is `CLAUDE_CONFIG_DIR` when the agent has a profile, else `~/.claude` |
| codex | `<CODEX_HOME>/sessions/**/rollout-*.jsonl` | same profile rule |
| agy | — | **none. See §5** |

An agent's cwd is `/workdir/<agent>`, and its profile is the `profile` key —
`flock.tmuxhost` already reads it, so the resolution is known code.

⚠ **Take the newest file and expect it to change.** A CLI starts a new session
file when it restarts, so the file being tailed is not stable for the life of an
agent. When the newest file differs from the one you were reading, **start at
offset 0 of the new file** — do not carry the old offset across.

## A2. Polling, in one pass

The router already runs; this is a step in its loop, not a new process.

⚠ **One pass covers the tenant.** Keep a byte offset per agent in Redis, read
only what is new since last time, and never re-read a whole file. A session file
grows to megabytes over a day.

⚠ **A per-agent tailer process is the thing not to build** — that is a daemon
per agent, which is exactly what the kicked-adapter design exists to avoid.

Poll interval: start at 2s. It is a typing indicator, not a trade feed.

## A3. The stream

```
  <prefix>:agent:<name>:activity     XADD, MAXLEN ~ 1000
```

A **Redis Stream**, for the same reason as the mailbox: several readers at their
own positions, and a cursor to resume from. One field, `event`, carrying:

```json
{ "v": 1, "agent": "sme-2", "ts": "…", "kind": "tool", "tool": "Bash" }
```

`kind` is a **small, closed set** — `input`, `output`, `tool`. `tool` is present
only for `kind: tool`.

⚠ **Keep the vocabulary tiny and resist normalising further.** Every CLI-specific
record type mapped into a rich common model is a per-CLI, per-version commitment
— the same trap as parsing footers. Three kinds is enough for a typing indicator
and a stalled check. If something genuinely needs more, that is a later
conversation with a use case attached.

## A4. What must never be emitted

⚠ **Tool names only. Never arguments, never content.** A `Bash` argument is a
command line; a `Write` argument is file content; a prompt is the user's words.
This feed is designed to leave the tenant — an app subscribes to it over HTTP —
so anything in it is out.

⚠ **Not the file paths either.** `Read /workdir/sme-2/secrets.env` tells an
observer more than "the agent read a file" needs to.

If content is ever wanted, it is a separate opt-in with its own decision, not a
field someone adds because it was easy.

---

# B. The route — `api`

```
GET /agents/{agent}/activity?after=<cursor>&limit=100    catch-up
GET /agents/{agent}/activity/stream                      live, SSE
```

Same cursor and SSE shape as `/messages` — entry id is the cursor,
`Last-Event-ID` resumes. **Reuse the messages implementation**; if the two differ
in any way a client can observe, one of them is wrong.

⚠ **Available for any tmux agent**, not only api clients — this is state about an
agent, like `/board`, not a client's mailbox. An agent with no feed returns an
empty list, not a `404` (§5).

Document it in `API.md`: what the three kinds mean, that arguments are
deliberately absent, and that **the absence of activity is not an error**.

---

## 5. agy produces nothing, and that is the honest answer

agy keeps no equivalent session file — it has `conversation_summaries.db` and
protobuf under `implicit/`, neither of which is a documented append log.

⚠ **An agy agent's activity stream is empty, and the docs must say so.** Do not
approximate it from window output, do not infer it from token counts it does not
write. Same rule as the watchdog admitting agy has fewer signals: **a feed that
silently omits a third of the fleet is worse than one that says which third.**

## 6. Done when

- an agent working produces `tool` events naming the tools, live
- `GET /agents/<name>/activity` returns them with a cursor; `?after=` returns
  only what followed
- `/activity/stream` delivers an event that happens while the connection is open
- **no tool argument, file path or message content appears anywhere in the
  stream** — grep it and be sure
- a restarted CLI is picked up from its new session file, not stuck on the old one
- an agy agent returns an empty list and `200`
- the router's loop is not measurably slower with the poll in it
- `API.md` documents the route, the three kinds, and the agy gap

## 7. Reporting

`jira done`, then message `architect` with the key, the exact event shape, and
status. ⚠ The event shape is a contract between two lanes and a client — state it
exactly, and do not change it after the fact without saying so.
