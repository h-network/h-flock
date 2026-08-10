# Build 34 — three defects that fail quietly

> Small, and deliberately grouped: each one is the code being right while
> something around it hides a failure. That class has cost us more than any
> logic bug this week.
>
> **Base on `main`.** Branch `<lane>/build-34-<piece>`, push to origin.

## 1. `tmuxhost` strands the last window — `tmux`

```
  for window in sorted(list(existing_windows)):
      if window not in roster_agents:
          if len(existing_windows) > 1:
```

The guard keeps the session alive, which is right. The consequence is that a
retired agent's window **persists forever if it is the only one left** — and a
window with no roster row is exactly the "unaddressable" state that makes an
agent look present when it is gone.

⚠ **Decide, do not just patch.** Either keep one placeholder window that is
obviously a placeholder (the `__init__` shape the empty-roster path already
uses), or find another way to hold the session open. What must not remain is a
*retired agent's* window masquerading as an office.

## 2. Trust setup swallows every error — `tmux`

`write_agent_guide` and all three `ensure_*_project_trusted` wrap their work in a
bare `except Exception: pass`. A caller cannot tell success from silent failure.

⚠ **This is how the profile-blind trust bug hid.** Seeding failed quietly, every
profiled agent sat at a trust picker, unreachable, and presence read `idle`
because idle is what a prompt looks like.

- these must not raise into a delivery path — that part of the original decision
  stands
- but a failure must be **visible**: a lifecycle `error` record naming the agent,
  the file, and what failed
- ⚠ **do not log inside an agent's window.** `office` is quiet now for exactly
  this reason (`HLD` §10a); these run in the host, so the container log is right

## 3. The console audits one door of two — `api`

`audit.jsonl` records what passes through the console proxy. Anything using the
tenant api token directly is invisible to it.

⚠ **Measured:** a plumbing run enrolled a client and put
`[message from telegram] hello from the app` into an operator's terminal, and the
audit log showed nothing but logins. The operator asked who sent it and the audit
trail could not answer — which is the one question it exists for.

Two honest options, and I want the reasoning either way:

- **widen it** — the api already logs every envelope (`sent`, `popped`,
  `forwarded`). An audit view could read the tenant's own log rather than only
  the console's, and then it covers both doors
- **narrow the claim** — rename it to what it is, an *operator action log*, and
  say plainly in the README that traffic using the api token directly does not
  appear

⚠ **What is not acceptable is the current shape**: a thing called an audit trail
that misses half the traffic without saying so.

## 4. Done when

- a retired agent's window cannot outlive its roster row
- a trust or guide failure produces a record naming agent, file and reason —
  and still never breaks a delivery
- the audit either covers both doors or stops claiming to
- ⚠ **each one demonstrated**, not asserted: force the condition and paste what
  happened. Two of these are invisible-failure bugs, so a test that only proves
  the happy path proves nothing

## 5. Reporting

`jira done`, then message `architect` with what you changed, what you forced, and
what you saw.
