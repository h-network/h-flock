# Audit 04 — the docs against builds 26–28

> Rules unchanged: [`AUDIT-01`](AUDIT-01-docs.md) §1 and §3, and
> [`AUDIT-02`](AUDIT-02-docs.md) §5 (hunt absolute claims).
>
> **Base on `main`.** Branch `<lane>/audit-04-docs`, push to origin.

## 1. The gap, measured

```
                        watchdog  alerts  blocked  office status
  CONTRACTS.md                 0       0        0              0
  LLD-container.md             0       0        0              0
  LLD-api.md                   0       0        0              0
  LLD-tmux-host.md             0       0        0              0
  HLD.md                       1       0        0              0
  README.md                    1       0        0              0
  API.md                       4       5        0              0
```

⚠ **`CONTRACTS` is at zero and it is the file that pins keys.** Two new ones
exist — `<prefix>:alerts` (tenant) and `<prefix>:agent:<n>:blocked` (per-agent) —
and the classified resource set that the teardown test enforces has changed.

⚠ **`LLD-container` is at zero and the watchdog is a new process.** That document
describes what runs in a tenant, and a whole daemon started by the entrypoint is
missing from it.

⚠ **`README` says the watchdog is not built.** It is. That line is now wrong
rather than merely stale.

## 2. What landed

- **`office status`** — presence, the open ticket and its age, last activity, per
  agent. A **pull**: nothing is pushed at anyone. Reports `blocked` when set
- **the lead's guide** gained: check `office status` before assigning, hold work
  from a `blocked` agent, **do not try to fix the agent**
- **the watchdog** — its own process, not the router's pass. Three signals
  together or silence; credentials warned per account
- **alerts** — `<prefix>:alerts`, plus `GET /alerts` and `/alerts/stream`.
  **No envelope to any agent**, deliberately
- **`blocked`** — written by the **router** from its own delivery verdict, not by
  the watchdog and not from a screen
- **no `capture-pane` outside the session door**, which is for rendering a
  terminal to a person

## 3. Two claims that must be stated carefully

⚠ **`blocked` does not mean "stuck".** It means *a delivery was judged unverified
and nothing has been consumed since*. It catches a trust picker and a wedged
process; it **misses** a CLI that records input it does not act on — a login
prompt or a modal picker. Measured twice. If your file describes `blocked`, it
must not imply it catches everything.

⚠ **The watchdog alerts a human, never an agent.** If a doc says it messages the
lead, that is the first draft and it was reversed: telling an agent launders
"reports, never repairs", and a lead messaging a stalled agent produces the
activity that resets the very silence timer that surfaced it.

## 4. Who audits what

| lane | fix these |
|---|---|
| `bus` | `LLD-bus-and-router.md`, `PLAN-agent-tools.md` |
| `tmux` | `LLD-adapter-tmux.md`, `LLD-tmux-host.md`, `LLD-container.md`, `PLAN-profiles.md` |
| `api` | `LLD-api.md`, `LLD-session.md` |

`HLD`, `README`, `CONTRACTS`, `API.md`, `PLAN-boards`, `TODO`, `SPRINTS-next` are
report-only — mine. `BUILD-*`, `AUDIT-*`, `REVIEW-*`, `VERIFIED-*` are records.

⚠ **`bus`: the watchdog is a new module with no LLD at all.** Decide and say
which — a section in `LLD-bus-and-router`, or that it needs its own file. Do not
create a new LLD without saying why.

## 5. One process change, because audit 03 exposed it

Last time the lanes fixed their LLDs, I fixed the specific lines reported, and
`HLD` plus `README` stayed at zero — because **report-only files have no owner in
this process**. I caught it by re-measuring afterwards.

⚠ **So: re-measure at the end.** Run the §1 table again before reporting done. A
column still at zero is either a real gap or a deliberate silence, and saying
which is part of the job.

## 6. Reporting

What you fixed, what you found in files you do not own, what you checked and
found correct, **and the re-measured table**.
