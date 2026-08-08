# Next sprints

> Four topics, decided in outline. ⚠ **Partly built since:** pausing an office
> shipped in build 08 as `PauseAgent`/`ResumeAgent`, and the broadcast row in §1
> is `office broadcast`. The lead being positional, role-based names, `cloneToAll`
> and the watchdog are still outline only.

## 1. Authority, naming, and pausing an office

### The lead is positional

**The first agent is always the architect.** No configuration, no
`AGENT_LEAD` variable to keep in step — position in the roster *is* the answer.

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

**Not `alice` / `bob` / `carol` — `frontend`, `backend`, `systems`, `networking`,
`redis`.** What the engineering team is responsible for.

This is not cosmetic. An agent told *"you are `backend`, your peers are
`frontend` and `redis`"* knows what it is for and who to ask, from its name
alone. `alice` conveys nothing and needs a guide to say what a name could have
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

### `StopAgent` must clear the per-agent state

⚠ `letGo` deletes the roster field and the launch key. It must also **`DEL` the
`paused` marker**, or pausing an agent, retiring it, and hiring the same name
again brings it back paused with nothing saying why.

The general rule, since this will recur: **any per-agent key `StopAgent` does not
clear becomes a booby trap for the next agent with that name.** Roster field,
`launch`, `profile`, `paused` — all of it goes. Queues and boards are data and
are a separate question; state is not.

## 2. `cloneToAll`

Wanted. Design is in [`TODO.md`](TODO.md) — three small changes to h-office's
version: roster from `flock.bus.roster` instead of `offices.yaml`, filter to VAB
`tmux`, root at `/workdir/<agent>` instead of `/workspace`.

Keep their fetch-once-then-clone-locally trick verbatim; cloning N times over the
network downloads the same objects N times.

**No longer blocked** — it needs git credentials in the container, which
`container/seed-home.sh` now delivers.

## 3. The watchdog, and folding `verify` into it

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
