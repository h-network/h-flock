# Onboarding — the `tmux` lane

> One file, two halves: what you own, then a first task chosen because it is
> unresolved. Delete this file once the task is done; it is not a permanent doc.
>
> **Base on `main`.** Branch `tmux/sim-poll`, push to origin.

## 1. Read in this order, and stop when you can answer the question

1. `docs/HLD.md` — the whole system in one pass. ⚠ **§10 is the ceiling on every
   security idea:** the container is the boundary, and nothing inside it is.
2. `docs/LLD-tmux-host.md` — yours.
3. `docs/LLD-adapter-tmux.md` — yours. The adapter is **kicked per delivery and
   exits**; it is not a daemon, and reintroducing one is the thing an earlier
   build existed to remove.
4. `docs/LLD-container.md` — yours, because `entrypoint.sh` is yours. §3.1 is
   recent and explains a mistake worth not repeating.
5. `docs/CONTRACTS.md` §3 — the five log records of one delivered envelope.

**The question:** an envelope addressed to an agent arrives at a tmux pane —
name every component it passes through and what each one may assume. If you
cannot, keep reading; if you can, stop.

## 2. What you own

| | |
|---|---|
| `src/flock/tmuxhost/` | windows exist because this polls the roster and makes them |
| `src/flock/tmux/ops.py` | every tmux invocation, window creation, guide and trust seeding |
| `container/entrypoint.sh` | tenant boot order, roster seeding, both guards |

⚠ **`entrypoint.sh` is the boot path.** A fault here is not a failing endpoint,
it is a tenant that never starts. Changes to it get a lab run, always.

## 3. How this lane reports

Four things, learned the hard way, each from a real incident in this repo:

- **State the commit you worked from.** Two lanes have audited stale trees and
  reported confidently about code that had already changed.
- **A claim needs a citation that exists.** A previous holder of this lane
  returned twelve `CORRECT` verdicts citing files that were not in the
  repository, and once reported a completed build with a clean workspace and no
  commits. That is the failure mode this lane is watched for.
- **Done means pushed**, and means the tenant still boots — not that the new
  behaviour proves itself. Build 36 forced its refusal correctly and shipped a
  guard that refused every container, because nobody started a tenant the
  ordinary way afterwards.
- **"I could not reproduce it" is a complete answer.** It is worth more than a
  fix that was never demonstrated.

## 4. First task — an open question, not a known answer

⚠ **I could not close this. There is no answer to pattern-match.**

`container/sim-blocked.sh` passes 19/19 against a plaintext tenant. Against a
TLS tenant its window checks fail:

```
FAIL  sim-wedged window created  : expected [0] got [1]
FAIL  sim-nologin window cleaned up : expected [0] got [1]
```

What is known, and no more than this:

- both `poll_window_ready` and `poll_window_gone` run the **same** expression,
  `tmux list-windows -t $TENANT | grep -c " $agent"`
- they fail **together**, and `poll_window_gone` passes when no window exists —
  so "no window was created" does not explain it. Empty output does.
- the identical `StartAgent` returns `202` and creates the window when run by
  hand against that same tenant, seconds later
- it is **flaky, not deterministic**: the cleanup polls passed in one run and
  failed in the next, same tenant, same script
- reproducing it needs a TLS tenant: `README` "certificates must exist before
  the tenant boots" — create, `docker cp`, start

**Deliverable:** a diagnosis with evidence, and a fix if the fault is in the
script. If the fault is in `list-windows` under load, or in `docker exec`, say
so and show it. If it does not reproduce, say that and show what you ran.

⚠ **Do not fix it by making the poll retry harder.** Masking a helper that
returns empty output is how this stays unexplained.

## 5. Reporting

`jira done`, then message `architect`: the commit you worked from, what you
found, what you ran to find it, and status.
