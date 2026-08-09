# Build 22 — telling the truth about state

> Two places the system reports something it has not checked: keys that outlive
> the agent they belonged to, and a login check that looks at one account.
>
> **Base on `main`.** Branch `<lane>/build-22-<piece>`, push to origin.

---

# A. `StopAgent` leaves five keys behind — `bus`

## A1. What is left

`letGo` clears the roster field, `launch`, `profile` and `paused`. Every key
added today survives it:

```
  activity          a re-hire inherits the previous agent's history
  activity.offset   a byte offset into a session file that no longer exists
  presence          says "working" about an agent retired mid-task
  pending.verify    markers judged against a different agent's activity
  delivering        a stale busy tag serialises that agent's deliveries forever
```

⚠ **`presence` bites first.** Retire an agent while it is working, hire the name
back, and it reads `working` with a `since` from before it existed — a lie a
client renders as a typing indicator that never stops.

⚠ **`delivering` is the dangerous one.** The busy tag exists so two adapters do
not paste into one window at once. A stale one left by a retirement means the
next agent with that name may never be delivered to at all.

## A2. The fix is not a longer list

A list somebody remembers to extend is what produced this. **Put the set in one
place and make forgetting fail the suite.**

- `flock.bus` gains the canonical set of **per-agent** resources and a
  `purge_agent(r, *, pod, tenant, agent)` that deletes all of them.
- `StopAgent` calls it, for both VABs — a client's `inbox` is per-agent too.
- **A test enumerates every `resource="…"` literal under `src/`** and asserts
  each is either in the per-agent set or in an explicit tenant-level set
  (`roster`, `lead`, `window.log.offset`).

⚠ **That test is the actual deliverable.** The five `DEL`s fix today; the test
is what stops build 23 adding a sixth. A new resource then fails the suite with
"classify me", which is the cheapest possible reminder.

⚠ **Queues and boards stay.** `ingress`, `egress`, `dead` and `tasks.*` are
**data**, and `SPRINTS-next` §1 already decided a board survives `letGo`. This
build does not revisit that — it clears *state*, not work.

## A3. Done when

- `letGo` leaves none of the five behind
- retiring a working agent and re-hiring the name reports `idle`, not `working`
- a delivery to the re-hired name is not blocked by a stale busy tag
- the classification test fails when a new `resource="…"` is added and not listed
- boards and queues still survive `letGo`, as decided

---

# B. `seed-home.sh check` looks at one account — `tmux`

## B1. What it reports

It checks three fixed paths — `.claude/.credentials.json`, `.codex/auth.json`,
`.gemini/…/antigravity-oauth-token` — and says "logged in".

**Profile accounts are invisible to it.** A tenant with `AGENT_PROFILES=sme-2=work`
has `.claude-work`, which needs its own login because a profile *is* a separate
account. Measured: `check` reported all three CLIs logged in while `sme-2` sat at
*"Not logged in · Run /login"*.

⚠ **The command whose entire job is "which accounts still need a login" is blind
to accounts.** `setup.sh` prints its output under the heading *"Accounts still
needing a login"*, so it is not merely incomplete — it answers a question it was
not asked and looks authoritative doing it.

## B2. What it should do

Report **per account**, not per CLI: the default plus every `.claude-*` and
`.codex-*` directory present in the container.

```
  default   claude  logged in
  default   codex   logged in
  default   agy     logged in
  work      claude  NEEDS LOGIN
  work      codex   NEEDS LOGIN
```

⚠ **A profile dir with no credential is the normal state, not an error.** It is
what `seed_profile_dir` produces and it means "log in here once". Word it as work
to do, not as a fault.

⚠ **agy has no per-profile form** — one token at a fixed path. Show it once under
`default` and do not invent a per-account row for it.

## B3. Done when

- a tenant with a profile shows that account's rows separately
- an account with no credential reads `NEEDS LOGIN`, and `setup.sh`'s heading is
  then true
- a tenant with no profiles reads exactly as it does today
- agy appears once

---

## Reporting

`jira done`, then message `architect` with paths and status. ⚠ For §A, report the
**re-hire** result — retire a working agent, hire the name back, and say what
presence reads.
