# LLD — lanes

> **Status: describes a convention and one tenant's history, not a code
> module.** Every other `LLD-*.md` in this repo documents something that
> ships in `src/`; this one documents how the agents *building* `src/`
> organise themselves, so a future architect session doesn't have to
> re-derive it from `git log` the way this one did. If it drifts from
> reality, trust `office peers -i` / `office profiles` over this file — see
> §4.

## 1. What a lane is

`HLD` §3's "a lane own a module outright" is the whole idea: one agent, one
module, its own branch (`<lane>/<short-description>`). ⚠ **Updated
2026-08-30: a lane pushes its branch and tells the lead — it does not open
its own PR.** The lead opens the pull request into `develop`, reviews it,
and merges once CI passes; `develop` promotes to `main` on its own release
cadence. Nothing here is enforced by the framework — `office hire <name>` takes any name —
it is a working convention this tenant's operator and lead settled on, the
same way `office broadcast` vs. `destination: "all"` is a convention about
who counts as a colleague (`HLD` §6) rather than something the switch
polices.

## 2. Deriving lanes from history, not guessing

Real lane names are recoverable from merge commit titles, which this repo's
own convention names `<lane>/<description>`:

```
git log --oneline --merges | grep -oP "Merge \K[a-z0-9-]+(?=/)" | sort | uniq -c | sort -rn
```

⚠ **A lane can be renamed mid-project without becoming a second lane.**
`office` and `office-sme` looked like two lanes in that count until checked
chronologically (`git log --oneline --merges --reverse`) — every `office/…`
merge predates every `office-sme/…` merge, no interleaving, so it was one
lane renamed partway through, not two agents. Check for interleaving before
concluding a name split means a lane split.

## 3. This tenant's lanes

Nine lanes were originally hired for, mapped from the module table in `HLD`
§3 plus one cross-cutting exception. Two more split off since (`ports` from
`bus`'s original scope, `openshell` as a new port_type):

| lane | owns | maps to |
|---|---|---|
| `bus` | switch + `bus.doors.send`/tracking | `flock.bus`, `flock.switch` — `LLD-bus-and-switch.md` |
| `ports` | the generic port delivery framework | `flock.port`'s registry/dispatch/openers shared across port_types — `LLD-port-delivery.md`, split off from `tmux`'s original scope (§2's rename-vs-split test applies: this was a genuine split, `tmux` kept the tmux-specific delivery, `ports` took the generic framework `deliver_one` dispatches through) |
| `tmux` | the tmux server, windows, paste | `flock.tmuxhost`, `LLD-tmux-host.md` + `LLD-port-tmux.md` (the tmux-specific half of what used to be one doc with `LLD-port-delivery.md`) |
| `openshell` | disposable sandbox agents (`port_type: openshell`) | `flock.openshell`, the `openshell` branches of `flock.port`/`flock.control` — `LLD-port-openshell.md` |
| `api` | the REST door | `flock.api`, `LLD-api.md` |
| `interface` | the websocket door + bundled clients | `flock.session`, `LLD-session.md`, plus `clients/telegram` and `clients/web` (`SPEC-bundled-clients-and-exposure.md`) |
| `watchdog` | observation, alerts | `flock.watchdog`, `LLD-watchdog.md` |
| `office-sme` (= `office`) | the agent-facing command | `flock.office`, `LLD-office.md` — see the rename note in §2 |
| `testbed` | the tenant/container, plus CI infrastructure (added 2026-08-29, by the operator) | `flock.tmuxhost`'s container half, `LLD-container.md`, `setup.sh` — plus `.github/workflows/`, the dev-dependency declaration, the shared `tests/conftest.py` fixtures/doubles, and any real-service (e.g. Redis) integration harness; see `LLD-ci.md`. ⚠ **Not** ownership of every lane's own test files — each lane still writes and owns the tests for its own module (`bus` owns `test_bus.py`, `api` owns `test_api.py`, and so on); testbed owns the cross-cutting harness those tests run on, not the tests themselves. |
| `acceptance` | cross-cutting verification | no dedicated LLD — works from `TEST-SIGNOFF.md` and `SPRINTS.md` instead, since it verifies every other lane's output rather than owning a module |

`office` and `office-sme` are both live in this tenant's roster as separate
hires even though they're historically one lane — that was a deliberate
choice to have two workers on one module, not a misunderstanding of §2's
rename note. Coordinate between them rather than assuming either owns it
alone.

## 4. Live roster: ask the tenant, not this file

This document will not be updated every time someone is hired or retired.
For who is actually on the roster right now:

```
office peers -i      # colleagues, plus recognized api/control interfaces
office profiles      # every account, who's on it, who has no CLI account
```

## 5. CLI and account assignment

⚠ **The specific mapping below is a historical snapshot, not current
state — same caveat §4 already makes for the live roster.** Account/CLI
assignment changes with every hire/retire/reassignment, same category of
fact as who's on the roster at all. For the actual current split, run:

```
office peers -v      # framework + profile per peer
office profiles      # who's on which account
```

Two accounts existed in this tenant: `default` and `bussines`. ⚠ **Only
`claude` can be pointed at a second account without a manual step.**
`setup.sh` (~line 146) hard-blocks `agy` from anything but `default` —
`agy` keeps its state in `~/.gemini/antigravity-cli` and exposes no
equivalent of `CLAUDE_CONFIG_DIR` / `CODEX_HOME`, so `setup.sh` silently
resets its account back to `default` with a warning if asked otherwise.
`codex` is **not** hard-blocked the same way — it gets a per-profile
`CODEX_HOME` same as claude's `CLAUDE_CONFIG_DIR` — but unlike claude's
`CLAUDE_OAUTH_TOKEN_<PROFILE>`, there is no automated OAuth-token seeding
for a second codex account, so it works but needs an interactive login
`setup.sh` doesn't do for you. Caught and corrected by `office-sme` during
review of this document — verify against `setup.sh` yourself before citing
this section if it looks stale.

This tenant's split, decided with the operator: `bus` and `watchdog` on
`claude`/`bussines` (isolating the delivery-path lane's login from
everything else, and pairing it with the thing that observes it rather than
with `interface`, the other half of the bug both were hired to fix — see
`office-sme`'s and `bus`'s own history if the reasoning matters later).
`office-sme` also on `claude`, but `default`. `tmux`, `api`, `testbed` on
`codex`/`default`. `office`, `interface`, `acceptance` on `agy`/`default`.
None of this is load-bearing — it was a balance-and-isolate judgment call
for one specific incident, not a rule to keep re-applying without a reason.
