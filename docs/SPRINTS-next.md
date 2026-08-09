# Next sprints

> Four topics, decided in outline. ⚠ **Partly built since:** pausing an office
> shipped in build 08 as `PauseAgent`/`ResumeAgent`, and the broadcast row in §1
> is `office broadcast`. The lead being positional, role-based names, `cloneToAll`
> and the watchdog are still outline only.

## 1. Authority, naming, and pausing an office

### ~~The lead is positional~~ — SHIPPED in build 21

**The lead is the first name in `AGENTS`**, recorded once at boot as
`<prefix>:lead`, named in every agent's guide, and marked by `office peers`.
Verified with a first agent that does not sort first. The section below is the
reasoning that got there, including the alphabetical trap it walked into.

### The lead is positional — ⚠ except the roster has no position

**The first agent is always the architect.** No configuration, no
`AGENT_LEAD` variable to keep in step — position in the roster *is* the answer.

⚠ **Measured, and the word "position" is doing work the data cannot support.**
The roster is a Redis **HASH**, which has no order. Every "first agent" in the
codebase is `sorted(...)[0]` — `flock.tmuxhost` picking the first window since
the skeleton, and `office peers` marking the lead since build 20. So the lead is
the **alphabetically first** agent, not the one entered first at `setup.sh`.

```
  roster        zeus, backend, frontend       (setup.sh: agent #1 was zeus)
  sorted()[0]   backend                        ← the lead, silently
```

It works today because `architect` sorts early, which is luck rather than design.
h-office does not have this problem because it reads `offices.yaml`, a file that
*has* an order.

**Three ways out, none taken yet:**

1. **Say what is true** — the lead is the alphabetically first agent. Zero
   machinery, and `architect` keeps working. Surprising for anyone who names
   their lead `zeus`.
2. **Give the roster an order** — the entrypoint knows the `AGENTS` sequence.
   Costs a second key to keep in step with hire and letGo, which is the derived
   state `AGENT_PEERS` was removed for.
3. **Convention over position** — the lead is `architect` when present, else
   alphabetically first. No new state, but it is magic tied to a name.

⚠ Do not resolve this by adding `AGENT_LEAD`. That was specced, built and
reverted once already, and the reasoning below still holds.

Corroborated by h-office, which arrived at the same rule independently:

```python
# Lead defaults to the first roster agent (architect).
self.wd_lead = os.environ.get("WATCHDOG_LEAD", "")
```

This closes the question left open in [`TODO.md`](TODO.md) — and it is why the
earlier `AGENT_LEAD` spec was reverted. It was configuration for something that
does not need any.

⚠ Still rests on `producer` being unforgeable, which it is not (see
[`TODO.md`](TODO.md)). Shipping regardless is a deliberate trade — the
impersonator would be one of our own agents, and the alternative is an office
that does not function.

### Agents are named for responsibilities, not people

**Not `backend` / `frontend` / `systems` — `frontend`, `backend`, `systems`, `networking`,
`redis`.** What the engineering team is responsible for.

This is not cosmetic. An agent told *"you are `backend`, your peers are
`frontend` and `redis`"* knows what it is for and who to ask, from its name
alone. `backend` conveys nothing and needs a guide to say what a name could have
said. The guide, the roster and `peers` all get more useful for free.

⚠ Placeholders in every doc and example need replacing, and `setup.sh` should
suggest role names rather than defaulting to `agent-2`.

### Broadcast is two different things

Today "broadcast" means one thing. It is really two, and they should not share a
command:

| | |
|---|---|
| **a message to everyone** | conversation — "standup in five". `office broadcast`, exists |
| **a control signal to everyone** | `Ctrl-C` every window, stop every TUI. Does not exist |

The second is not a message and must not travel as one — it is keystrokes to
every pane, the way `flock.session` sends them, not envelopes to every ingress.

### Pause is not retire

`startAgent` supports `-r` / `--resume`, which makes a state we have no word for:

```
  hire / letGo     enrol and remove — the agent is gone, roster row deleted
  pause / resume   stop the CLI, keep the window, the home and the roster row
```

**You sometimes want to stop the office without dismantling it** — every agent
`Ctrl-C`'d, windows and homes intact, and later `startAgent --resume` in each to
pick up where it left off. `letGo` is the wrong tool: it destroys the thing you
wanted to come back to.

**Decided: pause is a window operation plus a marker. The roster is not
touched.**

⚠ Removing the agent from the roster would do the *opposite* of pause — it would
destroy the window. `LLD-tmux-host` §5: *a window with no agent in the roster is
removed*, so reconcile would kill exactly the thing you wanted to return to.
That is `letGo` with the keys left behind.

Leaving the roster row alone also dissolves the question of what happens to the
agent's tasks and other keys: **nothing keyed by the agent name needs touching,
because the agent still exists.** It simply is not running a CLI.

```
  pause backend    SET …:agent:backend:paused 1
                   send-keys C-c into the window

                   a kick arrives → the adapter sees the marker → exits WITHOUT
                   popping. Envelopes accumulate in ingress, durably, and the
                   depth is readable.

  resume backend   DEL the marker
                   send-keys "startAgent --resume"
                   then drain what accumulated
```

Same shape as the busy tag: a per-agent state key that **only the adapter
reads**, so the router stays ignorant and invariant 8 is untouched.

**Resume drains.** A kick that finds the marker set does nothing and is gone, so
after clearing the marker `resume` reads `LLEN` on the ingress and kicks that
many times. The agent gets everything it missed, back to back.

⚠ Waiting for the next unrelated message to shake one envelope loose is not a
simpler version of this — it is the wrong behaviour. An agent that was paused for
an hour should come back to its inbox, not to one message from it.

### `StopAgent` must clear the per-agent state — ⚠ and five keys have accrued since

`paused` is cleared now. **Five newer per-agent keys are not**, every one added
today:

```
  activity          the agent's feed — a re-hire inherits the old agent's history
  activity.offset   a byte offset into a session file that no longer exists
  presence          says "working" about an agent that was retired mid-task
  pending.verify    markers judged against activity from a different agent
  delivering        the busy tag — a stale one serialises deliveries forever
```

⚠ **`presence` is the one that bites first**: retire an agent while it is
working, hire the name back, and it reads `working` until something overwrites
it — with a `since` from before it existed.

This is exactly the rule below, now with instances. The fix is one `DEL`; the
lesson is that the list grows every time a build adds a key, so **the teardown
belongs next to whatever creates the key**, not in a list somebody remembers to
extend.

The original note: `letGo` deletes the roster field and the launch key. It must
also **`DEL` the `paused` marker**, or pausing an agent, retiring it, and hiring
the same name again brings it back paused with nothing saying why.

The general rule, since this will recur: **any per-agent key `StopAgent` does not
clear becomes a booby trap for the next agent with that name.** Roster field,
`launch`, `profile`, `paused` — all of it goes. Queues and boards are data and
are a separate question; state is not.

## 2. ~~`cloneToAll`~~ — SHIPPED in build 16

Wanted. Specified in [`BUILD-16-profiles-and-clone.md`](BUILD-16-profiles-and-clone.md)
§B — three small changes to h-office's version: roster from `flock.bus.roster` instead of `offices.yaml`, filter to VAB
`tmux`, root at `/workdir/<agent>` instead of `/workspace`.

Keep their fetch-once-then-clone-locally trick verbatim; cloning N times over the
network downloads the same objects N times.

**No longer blocked** — it needs git credentials in the container, which
`container/seed-home.sh` now delivers.

## 3. The watchdog, and folding `verify` into it

> ⚠ **Unblocked as of build 11**, when boards gave it something to read. There is
> now a **third** signal too — see *A third signal* below, which is the part that
> stops it crying wolf.

h-office's watchdog lives in the courier and is four settings:

| | default | |
|---|---|---|
| `WATCHDOG_STALL_SEC` | 600 | a task sitting in `doing` longer than this |
| `WATCHDOG_INTERVAL` | 30 | how often it looks |
| `WATCHDOG_SILENCE_SEC` | 300 | …**and** the window has been quiet this long |
| `WATCHDOG_LEAD` | first agent | who gets told |

The second signal is the whole insight, and their comment says why:

> A stalled task only alerts if the agent's window has ALSO been quiet this
> long — **a long build keeps printing, a wedged agent does not.**

On elapsed time alone it fired identically for a 15-minute rebuild and a wedged
agent, so the lead learned to dismiss it and then dismissed a real one.

### Where `verify` fits

[`TODO.md`](TODO.md) lists the missing `verify` step as a silent loss path:
`opened` is logged, the envelope is gone from Redis, and the text sits
unsubmitted in an input box. h-office measured roughly one delivery in ten before
adding `COURIER_VERIFY`.

**A watchdog could catch it from the other side.** A delivery produces terminal
output; an agent that received a message and then went quiet without producing
any is the same shape as a wedged one. That is cheaper than re-reading the pane
after every Enter, and it catches other failures too.

⚠ But it is *detection*, not prevention — the message still sits unsent until
someone acts. h-office does **both**: verify at delivery, watchdog for what
verify misses. Do not treat the watchdog as a replacement.

### A third signal: the CLIs count their own tokens

Two signals cannot separate **thinking hard** from **wedged**. A long
model call renders nothing and prints nothing — it looks exactly like a hung
process, and that ambiguity is what teaches a lead to ignore the alert.

**The CLIs write their own token counts to disk**, so the third signal is a file
read — no screen parsing, no API, nothing version-specific:

| CLI | where |
|---|---|
| claude | its session JSONL, per call |
| codex | `~/.codex*/sessions/**/rollout-*.jsonl`, last `token_count` event |
| agy | **nothing** — Antigravity does not persist counts |

Taken from h-office's `usage.py`, which already does exactly this to show usage
and estimated cost per agent. Cost is estimated — neither CLI records dollars, so
tokens are multiplied by a rate table.

**What the combination buys:**

| `doing` age | window | tokens | reading |
|---|---|---|---|
| old | quiet | **climbing** | working — a long call. Do not alert |
| old | quiet | **flat** | stuck. Alert |
| old | printing | either | working. Do not alert |

⚠ **It also catches the blocked-at-a-prompt case**, which the other two miss
entirely: an agent sitting on an approval dialog or a trust picker burns no
tokens and prints nothing, and is indistinguishable from a wedge on the first two
signals alone.

⚠ **agy has only two signals**, so it is more likely to produce a false alert.
Say so in the message rather than pretending otherwise — an alert that admits
what it could not check is one a lead keeps trusting.

⚠ **Read the file, never the screen.** Deriving an agent's state by parsing its
TUI is a per-CLI, per-version commitment that does not end: a comparable project
spends ~1,200 lines on it, needs a capability flag per provider for whether
detection is even possible, and its own comments admit some states are not
screen-detectable. h-flock has never read a pane to make a decision and this is
not the place to start.

⚠ **Do not gate delivery on any of this.** The same project only delivers mail
when its detector says a terminal is idle, so a misread does not merely mislabel
an agent — it silently stalls its messages. Ours delivers immediately and lets
the TUI buffer. The watchdog observes; it must never sit in the delivery path.

### A fourth thing to read: credentials expiring

The same shape as the token counts — a file read, nothing version-specific — and
the only alert here that is about the *future* rather than the present.

| CLI | field | usable |
|---|---|---|
| claude | `claudeAiOauth.refreshTokenExpiresAt` | yes |
| agy | `token.expiry` | yes |
| codex | — only `last_refresh` | **no expiry is recorded at all** |

⚠ **Alert on the refresh token, never the access token.** claude's access token
expires within *hours* and the CLI silently refreshes it — alerting on that would
fire constantly and correctly, which is precisely the cry-wolf failure this
section exists to avoid. What matters is the refresh token: when it goes, no file
copied from anywhere helps and a human has to complete an OAuth flow.

⚠ **One alert per account, not per agent.** A profile is a config dir is a
login, and several agents share one. Alerting per agent turns one expiry into N
identical messages.

⚠ **codex cannot be checked**, so say "unknown" rather than "fine". An alert that
quietly omits a third of the fleet is worse than one that admits the gap — same
rule as agy having only two liveness signals.

### Do not classify *why*

Report what is true — took work, has not finished, has not spoken, has not spent
a token — and let a person look. Every attempt to say *why* an agent is stuck is
where the cost goes, and it is the part that cannot be done from outside.

Prerequisite: the watchdog is task-shaped (`doing` column), so it needs boards.
The window-silence half needs only `presence`, which has no dependencies at all.

## 4. Profiles: the last link, and the logins

**Ten lines, `tmux`'s lane:** `flock.tmuxhost` reads the `launch` key for the CLI
but not the `profile` key. It must turn `profile` into `CLAUDE_CONFIG_DIR` and
`CODEX_HOME` in the window environment. Until then accounts are seeded and
selected but never used.

**The logins themselves** still need doing once per account, interactively.
`container/seed-home.sh out` then keeps them across rebuilds.

### Checked: NVIDIA OpenShell, and why it changes nothing here

`NVIDIA/OpenShell` treats credentials as named *providers* discovered from the
host shell and injected as environment variables:

```bash
openshell provider create --name my-claude --type claude --from-existing
openshell sandbox create --provider my-github -- claude
```

That is **API-key shaped**, and it does not solve the interactive login. Their own
GitHub tutorial says so:

> OpenShell provides the sandbox runtime, not the agent. **You must authenticate
> with your own account.** … Claude Code starts inside the sandbox. **It prints an
> authentication link. Open it in your browser** … **When prompted, trust the
> `/sandbox` workspace.**

So the browser flow *and* the trust prompt are exactly what we hit. Nobody has
made the first login painless.

**And we do not need them to.** The office's answer, proven in practice: log in
once, copy `.credentials.json`, done — no API keys, no provider mechanism.
`container/seed-home.sh` already does this for all three CLIs
(`.claude/.credentials.json`, `.codex/auth.json`,
`.gemini/antigravity-cli/antigravity-oauth-token`).

The one thing they have that we do not is direction: theirs is host → sandbox
only, because their sandboxes are meant to be ephemeral and re-authenticated.
`seed-home.sh out` is the half that makes a tenant survive a rebuild.

**Closed.** Nothing to build.
