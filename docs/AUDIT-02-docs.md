# Audit 02 — the docs against builds 11–13

> Same shape as [`AUDIT-01-docs.md`](AUDIT-01-docs.md) — **its §1 and §3 still
> apply and are not repeated here.** Read them.
>
> **Base on `main`.** Branch `<lane>/audit-02-docs`, push to origin.

## 1. What changed since audit 01

Three builds landed and only some docs know it. **Apps became participants**, and
that is the change with reach: a VAB that did nothing now has a delivery routine,
and the roster has rows that are not agents in any window sense.

- `deliver_api` no longer discards — it writes to a **mailbox**, one per client
- `StartAgent` takes a **`vab`**; `vab: "api"` enrols a client and makes **no
  window**, no home, no CLI
- clients are addressed and replied to **by name**, exactly like agents
- `office peers` / `office broadcast` filter `vab == "tmux"`, so clients are
  invisible to agents
- there is a **public API reference**, `docs/API.md`, written for people who
  cannot see this repository

## 2. The gap, measured

Counting mentions of clients or mailboxes across the docs:

```
  CONTRACTS.md            11    current
  TODO.md                  5    current
  LLD-bus-and-router.md     0    ← the switch doc does not know VAB api does anything
  LLD-adapter-tmux.md       0    ← describes the adapter, one of whose two routines is new
  LLD-container.md          0
  LLD-session.md            0
  LLD-tmux-host.md          0
```

⚠ **Zero is not automatically wrong.** `LLD-session` may have nothing to say
about mailboxes and should then say nothing. Judge each — a doc that is silent
because the subject does not touch it is correct, and padding it is worse than
leaving it.

The two that clearly need work are the first two: `LLD-bus-and-router` is where
the VAB concept is defined and where "adding a participant is adding a name" is
argued, and `LLD-adapter-tmux` describes an adapter that now has a second
delivery routine doing something quite different from pasting.

## 3. Who audits what

Unchanged from audit 01 §2.

| lane | fix these |
|---|---|
| `bus` | `LLD-bus-and-router.md`, `PLAN-agent-tools.md` |
| `tmux` | `LLD-adapter-tmux.md`, `LLD-tmux-host.md`, `LLD-container.md`, `PLAN-profiles.md` |
| `api` | `LLD-api.md`, `LLD-session.md` |

Shared docs — `CONTRACTS`, `README`, `API.md`, `PLAN-boards`, `TODO`,
`SPRINTS-next`, `BUILD-*` — are report-only, as before. `API.md` in particular:
it is written for external readers and one internal reference undoes it, so if
you spot one, report it rather than editing.

## 4. Anchors, current as of this build

If a doc disagrees with these, the doc is wrong:

- a participant is a **roster row and a name**; VAB says what is attached to the
  port, and now spans `tmux`, `api` and `control`
- **VAB `api` delivers to a mailbox** — one per client, capped, read by cursor
- **`StartAgent` with `vab: api` creates no window**; `StopAgent` on one removes
  the row and the mailbox and touches no tmux
- clients do not appear in `office peers` and receive no broadcast
- an agent replies to a client with `office send -a <client>` — **no special case
  exists on the window side**
- the mailbox is the **only Redis Stream** in the system; everything else is a
  LIST
- `POST` still returns `202`; **a reply may never come**

## 5. One thing to actively look for

⚠ **Claims of the form "the only", "always", "never" and "nothing else".** Those
are the sentences builds 11–13 broke, and they are the ones a reader trusts most.
`CONTRACTS` had two — *nothing else writes the roster* and *transitions are
`LMOVE`* — and both were false before anyone noticed. Grep your files for them
and check each one is still true.

## 6. Reporting

As audit 01 §5: what you fixed, what you found in files you do not own, and what
you were unsure about. `jira done` after the push.
