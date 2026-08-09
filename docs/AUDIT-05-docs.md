# Audit 05 — the docs against build 29 and the live run

> Rules unchanged: [`AUDIT-01`](AUDIT-01-docs.md) §1 and §3, and
> [`AUDIT-02`](AUDIT-02-docs.md) §5 (hunt absolute claims). Re-measure at the end
> — [`AUDIT-04`](AUDIT-04-docs.md) §5.
>
> **Base on `main`.** Branch `<lane>/audit-05-docs`, push to origin.

## 1. The gap, measured

```
                       enter-delay  idempotent  profile  verify-order  allowlist  digit-names
  HLD.md                         0           0        0             0          0            0
  CONTRACTS.md                   1           2        0             0          0            1
  LLD-adapter-tmux.md            1           0        0             1          0            0
  LLD-tmux-host.md               0           0        0             0          0            2
  LLD-bus-and-router.md          0           0        0             0          0            0
  LLD-watchdog.md                0           0        1             0          0            0
  LLD-container.md               0           0        0             0          0            0
  LLD-api.md                     0           0        0             0          0            0
  LLD-session.md                 0           0        1             0          0            0
```

⚠ **I called this audit unnecessary before measuring the right columns.** I ran
the table from audit 04 — `watchdog`, `alerts`, `blocked`, `office status` — and
those were current, so I concluded the docs were current. They were current *for
the previous build*. Everything below is real code on `main` that no document
describes. Measure the new thing, not the last thing.

## 2. What landed since audit 04

Seven of these came out of one live run with three real CLIs, which is why they
are behavioural rather than structural. **Each one was a bug first.**

- **`ENTER_DELAY = 0.5`** — the paste and the Enter are sent as two writes with a
  gap. Arriving together, a CLI takes the text and drops the submit
- **`create_window` is idempotent by name** — a second window with the same name
  made the agent **unaddressable**: tmux refused the ambiguous target and every
  delivery to it failed with `can't find window`
- **trust seeding is profile-aware** — `ensure_claude_project_trusted(cwd,
  profile=None)`. Blind to profiles, every profiled agent sat at the trust
  picker, unreachable, and presence read `idle` because idle is what a prompt
  looks like
- **verify is marked *before* the paste, not after** — a sub-second race. Six
  deliveries landed and five were read as unverified because the reply arrived
  before the marker did
- **verify skips by allowlist `{claude, codex}`, never a denylist** — the rule
  was "not agy", so a plain bash window got markers pasted into it
- **all-digit agent names are rejected** — tmux resolves `s:2` as window *index*
  2, so an agent named `2` addresses whatever window happens to sit there
- **agy's credential is `unknown`, like codex** — `token.expiry` is the *access*
  token, refreshed by the CLI itself. The watchdog was alerting on a timestamp in
  the past for an account working fine
- **`clients/`** — a Telegram bot and a browser UI, built from `API.md` alone

## 3. Three claims that must be stated carefully

⚠ **`ENTER_DELAY` is not a fix for slow terminals.** It is two writes because a
CLI's input handling coalesces them into one. If your file explains it as
"waiting for the terminal to be ready", that is wrong and invites someone to
tune it to zero on a fast machine.

⚠ **Idempotent means *by name*, not "creates once".** `create_window` may be
called repeatedly and must converge on one window with that name. The failure it
prevents is ambiguity, not waste.

⚠ **Seeded credentials go stale in place** — open, in [`TODO`](TODO.md). A CLI
refreshes its own token; a copy handed to it does not. This ended a live session
mid-run at 15:30. Do not describe seeding as though it is durable.

## 4. Who audits what

| lane | fix these |
|---|---|
| `bus` | `LLD-bus-and-router.md`, `LLD-watchdog.md`, `PLAN-agent-tools.md` |
| `tmux` | `LLD-adapter-tmux.md`, `LLD-tmux-host.md`, `LLD-container.md`, `PLAN-profiles.md` |
| `api` | `LLD-api.md`, `LLD-session.md` |

`HLD`, `README`, `CONTRACTS`, `API.md`, `TODO`, `SPRINTS-next` are mine.
`BUILD-*`, `AUDIT-*`, `REVIEW-*`, `VERIFIED-*` are records — do not edit them.

⚠ **`tmux` carries most of this audit.** Six of the eight items are yours, and
`LLD-container.md` is at zero across every column again.

⚠ **`clients/` is not yours to document.** It is a consumer and deliberately
absent from the framework LLDs. Do not add it to them.

## 5. Reporting

What you fixed, what you found in files you do not own, what you checked and
found correct, **and the re-measured §1 table**. A column still at zero is either
a real gap or a deliberate silence, and saying which is part of the job.
