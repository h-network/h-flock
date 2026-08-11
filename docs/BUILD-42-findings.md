# Build 42 — what running it found

Three lanes, three real tenants on the lab, scenarios committed under
`container/scenarios/`. Raw output is in each lane's results document.

⚠ **Every one of these is something reading could not find.** The 50-row audit
read the whole codebase twice, with two different models, and found none of them.

| # | finding | source | status |
|---|---|---|---|
| 1 | **The restart we recommend empties every board.** | bus | ✅ confirmed, reframed |
| 2 | **The session token still reaches the log**, despite the fix I accepted | api | ✅ confirmed in uvicorn's source |
| 3 | A delivery accepted with `202` is dead-lettered when a window is missing and never replayed | tmux | confirmed by two lanes |
| 4 | A peer's workdir is readable — as documented | tmux | confirmed, deliberate |

## 1. The restart we recommend empties every board — `bus`

Measured twice with sentinels: a string and an untouched ingress list existed
before `docker restart` and were gone after the same container returned healthy.

```
before_restart sentinel=[restart-1786483567-3696390] queued=1
after_restart  health=healthy sentinel=[] queue_contains=0 queue_depth=0
```

⚠ **The persistence loss itself is deliberate and documented.** Redis runs
`--save '' --appendonly no`, and `LLD-container` §7 says "a skeleton loses its
queues on restart, which is fine". `bus` ranked this critical without that
context.

**The defect is the guidance, and it is worse than the raw finding.**
`seed-home.sh:70` tells an operator, in the ordinary course of installing
credentials:

```
or  docker restart <container>                   (whole tenant)
```

offered beside `office pause/resume`, which is annotated *"keeps the agent, its
board and its queue"* — implying, by contrast, that the restart costs something
smaller than every board in the office.

⚠ **A board is not a queue.** The documented decision covers losing in-flight
frames. Tickets are *work*: what an agent was asked to do, what it is doing, what
it finished. Nothing says restarting destroys that, and we recommend it.

`setup.sh:338` also restarts automatically — that one is fine, and says why:
the tenant is seconds old and holds no work.

**Fix, in order of value:** say what the restart costs where it is recommended;
prefer `pause/resume`; then decide whether boards deserve persistence now that
they carry real work. ⚠ **Persisting boards is a design change, not a bug fix**
— it is the operator's call, not a lane's.

## 2. The session token still reaches the log — `api`

I accepted a fix for this in wave 3 and it was incomplete. `access_log=False`
silences uvicorn's *access* logger; the handshake line comes from a different
one — `uvicorn/protocols/websockets/websockets_impl.py`:

```python
self.logger.info(
    '%s - "WebSocket %s" [accepted]',
    get_client_addr(self.scope),
    get_path_with_query_string(self.scope),   # ← includes ?token=…
```

Observed on the tenant:

```
INFO: 127.0.0.1:52310 - "WebSocket /session?token=<REDACTED-TOKEN>" [accepted]
```

That token grants `Command` execution in any agent's window, and it is now in
the tenant's stdout — the same stream an operator reads and ships.

⚠ **`tmux`'s cross-read flagged that the token appeared in `api`'s results**, and
following it up produced a smaller and more interesting answer than it first
looked. The value is the **example token from `docs/API.md`**, committed there
when the API reference was written — `api` reused the documented sample rather
than pasting a live secret, and no real credential was exposed.

⚠ **I got this wrong first**, and recorded it here as a live token leak before
checking `git log -S`. Two lessons, both cheap: **a realistic-looking example
secret in documentation will be reused as a real one and then reported as a
leak** — `docs/API.md` now uses `<YOUR_API_TOKEN>` — and **a claim about a secret
deserves the same "check it against the tree" rule as any other finding.**

**Fix:** stop the token appearing in a URL at all. A short-lived ticket minted
by the api door and exchanged on the socket keeps browsers working without ever
putting the long-lived token in a query string. Silencing another logger is
whack-a-mole — this is the second logger found in two days.

## 3. Accepted, then dead-lettered, never replayed — `tmux`

Two envelopes accepted with `202` were dead-lettered `window_missing` and not
replayed, though the window recovered moments later. Both `tmux` and `bus` read
the raw output and agree on what it is: **an availability loss window**, not a
false success and not an observability failure. The client was told `202` and the
message never arrived.

## 4. A peer's workdir is readable — `tmux`, deliberate

Confirmed twice, and consistent with `HLD` §10: the container is the boundary and
nothing inside it is. Recorded so the claim stays honest rather than closed
quietly — and it is exactly how the codex auditors wrote into the lead's clone.

## What could not be made to fail

⚠ **Worth as much as the findings.** Reported without padding:

- **broadcast storm** — ten broadcasts, five app recipients: `inbox=10
  matching=10` each, source egress drained, no payload in the log
- **retained egress** — an absent agent's queue held, and on re-enrolment
  delivered exactly `popped`, `forwarded`, `received`, `opened`
- **concurrent hire of one name** — two runs, last writer settled, exactly one
  window
- **credential exposure in a pane** — no API token or Redis URL reachable from a
  tmux pane environment

## What nobody could run

- hours-long retention, presence cost and spool truncation
- disk fill
- `SIGKILL` inside the sub-millisecond window between `BLPOP` and its log record
- real credentialed model work — the disposable tenants had no seeded account
