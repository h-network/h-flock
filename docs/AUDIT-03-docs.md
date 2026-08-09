# Audit 03 — the docs against builds 18–25

> Rules unchanged: [`AUDIT-01`](AUDIT-01-docs.md) §1 and §3 still apply and are
> not repeated. [`AUDIT-02`](AUDIT-02-docs.md) §5 — hunt absolute claims — applies
> too, and caught four last time.
>
> **Base on `main`.** Branch `<lane>/audit-03-docs`, push to origin.

## 1. The gap, measured

Mentions of each subsystem, per document:

```
                        activity  presence  verify  window.log
  HLD.md                       0         0       0           0
  LLD-bus-and-router.md        0         0       0           0
  LLD-api.md                   0         0       0           0
  README.md                    0         1       0           0
  CONTRACTS.md                 2         0       2           2
  API.md                      12         3       0           0
```

⚠ **The router grew four jobs and its own LLD mentions none of them.** It tails
session files, samples presence, judges verify markers, trims two lists and
truncates the window spool — all on the pass that document describes as popping
egress and writing ingress.

⚠ **`API.md` is the only one that kept up**, because `api` updated it as they
built. That is the exception, not the pattern.

## 2. What landed since audit 02

- **activity** — the router tails CLI session files into a per-agent Stream;
  `GET /agents/{a}/activity` and `/stream`
- **verify** — the adapter marks a delivery, the router judges it against a later
  `input` event, reports `delivery_unverified` and **never retries**
- **presence** — `working` / `idle` / `unknown`, on `GET /agents/{agent}`
- **the window log** — `office` in a window writes to a file the router tails, so
  `sent` finally reaches the log. **A delivered envelope leaves five records, not
  four**
- **the lead** — `<prefix>:lead` from the first name in `AGENTS`, named in every
  guide, marked by `peers`
- **teardown** — `StopAgent` purges per-agent state; a test classifies every
  resource literal
- **retention** — `BOARD_DONE_MAX`, `DEAD_MAX`, `WINDOW_LOG_MAX_BYTES`
- **an unknown agent is `404`**; `all` is exempt because it is not a roster member
- **`AssignTask` is gone**
- **invariant 7 changed shape**: *nothing in the **data path** reads a terminal;
  observation may look and may only report*

## 3. Who audits what

| lane | fix these |
|---|---|
| `bus` | `LLD-bus-and-router.md`, `PLAN-agent-tools.md` |
| `tmux` | `LLD-adapter-tmux.md`, `LLD-tmux-host.md`, `LLD-container.md`, `PLAN-profiles.md` |
| `api` | `LLD-api.md`, `LLD-session.md` |

`HLD.md`, `README.md`, `CONTRACTS.md`, `API.md`, `PLAN-boards.md`, `TODO.md`,
`SPRINTS-next.md` are **report-only** — mine to apply. `BUILD-*`, `AUDIT-*`,
`REVIEW-*` and `VERIFIED-*` are records; do not rewrite them.

## 4. Two things worth checking beyond your own files

⚠ **Invariant 7 is quoted in several places in its old form.** *"Nothing reads a
terminal to make a decision"* is now *"nothing in the data path reads a
terminal; observation may look and may only report."* If your file states it,
state the new one — the difference is the whole reason a watchdog may scrape and
an adapter may not.

⚠ **"Four records" may survive somewhere.** It is five. The arithmetic never
worked; it read as true only because `sent` went to a pane.

## 5. Reporting

As before: what you fixed, what you found in files you do not own, and what you
checked and found correct. **The last of those is not optional** — I cannot tell
a reviewed section from a skipped one without it.
