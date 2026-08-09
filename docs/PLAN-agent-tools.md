# Plan — the agent-facing tools

> **Status: built.** One `office` command replaced both the generic `send` and
> the first generation of separate agent commands.

## 1. Why one command name, with focused verbs

`send --kind StartAgent <agent> --payload '{"agent":"networking"}'` requires an
agent to know that kinds exist, what they are called, and what each payload
takes. That is the envelope model — ours, not theirs.

A focused verb needs none of it: `office hire networking` says what the agent means.
The shared `office` prefix matters just as much. The original `sendMessage`
collided with Claude Code's own `SendMessage` tool; task-shaped names collide
with its task tools too. One collision-resistant namespace fixes the class of
problem rather than chasing names one at a time.

There is no generic envelope command on an agent's `PATH`. `kind` remains on
the library call and the HTTP door for components that genuinely speak the
envelope protocol.

## 2. The surface

| Command | Does | Envelope or state underneath |
|---|---|---|
| `office send -a <agent> <text>…` | message one agent | `Message` |
| `office broadcast <text>…` | message every terminal peer | N × `Message` |
| `office peers` | list peer agents | roster read |
| `office status [<agent>]` | show tmux-agent presence, open work and last activity | roster, presence, blocked and board reads |
| `office hire <name> [--cli <cli>]` | enrol and start an agent | `StartAgent` to `host` |
| `office letGo <name>` | retire an agent and clear lifecycle state | `StopAgent` to `host` |
| `office pause <name>` | stop the CLI without retiring the agent | `PauseAgent` to `host` |
| `office resume <name>` | restart the CLI and drain its queued kicks | `ResumeAgent` to `host` |
| `office add -a <agent> -t <title> -d <brief> [-p <priority>]` | add a ticket | `AddTicket` |
| `office list [-a <agent>\|--all]` | list ticket IDs and titles | four board lists |
| `office take [<id>]` | pull a todo or held ticket into doing | board move |
| `office done [<id>]` | finish the open ticket | board move |
| `office cancel [<id>]` | finish it as cancelled | board move |
| `office hold [<id>]` | park the open ticket | board move |
| `office delete <id>` | remove one ticket | board removal |
| `office cloneToAll <repo-url> [-a <agent>,…] [--dry-run]` | clone one repository into terminal-agent workspaces | roster and filesystem |

Every subcommand has environment-free `--help`. Message text after the recipient
is literal: flags inside a message are data, so an agent can explain an `office`
command to another agent without `argparse` consuming the inner `-a`.

## 3. Broadcast and discovery

`office broadcast` takes no recipient. It resolves roster members whose VAB is
`tmux`, removes the sender, and sends one `Message` to each. It does not use
`recipient: all`, and never reaches any `api` client or the `host` control
participant. The bus's
reserved broadcast address remains available to protocol clients such as
`POST /agents/all/envelopes`, where the router fans out to the whole roster.

Filtering in the command is deliberate: it already knows that a room message is
for terminal agents, while the router must remain ignorant of VAB values. N
sends of a small envelope on loopback are cheaper than teaching the switch what
a conversational broadcast means.

`office peers` applies the same tmux-only filter. Peer membership is live state,
so it is read from the roster rather than copied into a window. It reads the
tenant's `<prefix>:lead` marker and labels that roster member rather than
assuming the lexically first name is in charge. `AGENT_PEERS` does not exist.

`office status` is the matching live-state view for work assignment. With no
argument it lists every tmux participant, including the caller; with a name it
prints one or errors if that name is not a tmux agent. Each row combines current
presence, the one `doing` ticket and its age, and last activity. An unknown feed
is reported as unknown rather than idle. If the router's `<prefix>:blocked` hash
exists, `blocked` replaces the displayed presence state.

⚠ **That word is deliberately narrow.** It means a delivery was judged
unverified and nothing has been verified since, not that the agent is known to
be stuck. A CLI can record input without acting on it at a login prompt or modal
picker; that delivery verifies and the state remains clear. `office status` is
a read only: it never creates, clears or repairs any of these signals.

Named app clients are roster participants with VAB `api`, but they are not
terminal peers: they have a retained mailbox and no window, home or CLI. The VAB
filter therefore keeps them out of both `office peers` and conversational
broadcasts. Direct addressing needs no special verb. An agent replies to a
client exactly as it replies to another agent:

```
office send -a telegram here is the answer
```

The router resolves `telegram` like any other name; the adapter's `api` routine
stores the envelope for the app to read. This sameness is the payoff from making
VAB a property of the roster port rather than of the sender or envelope.

## 4. Lifecycle is still bus traffic

The lifecycle verbs do not call control openers directly. They send
`StartAgent`, `StopAgent`, `PauseAgent` and `ResumeAgent` envelopes to `host`.
That keeps the CLI and API on the same path and leaves `flock.office` dependent
only on the shared `flock.bus` library.

⚠ **Do not call enrolment `startAgent`.** The base image already ships
`startAgent`, which launches a CLI in the current window. `office hire` enrols a
new agent and creates a new window: same tempting name, opposite operation.

`office hire` deliberately enrols only tmux agents. App clients use the same
`StartAgent` kind through the REST door with `vab: "api"`; that control path
creates only their roster row. Giving terminal agents a VAB flag would expose a
hosting decision their focused tool does not need.

Pause is not retirement. It preserves the roster row, window, queues, board,
home and address while stopping the CLI. Letting an agent go removes desired
state before killing the window so tmux-host reconciliation cannot recreate it.
It purges every classified identity-state resource (including launch, profile,
pause, mailbox, activity, presence and pending verification) while retaining
queues and board data for a later hire of the same name.

`office cloneToAll` is the filesystem-shaped exception to the otherwise
message-and-state surface. It selects tmux participants from the live roster,
fetches the repository once, clones subsequent workspaces locally, and resets
every clone's `origin` to the supplied upstream URL. Existing target directories
are skipped; `--dry-run` performs no writes.

## 5. Accounts arrive through profiles

`office hire` currently selects only `--cli`. It deliberately has no
`--profile`: a profile is an account/email and a non-default one can require an
interactive login. [`PLAN-profiles.md`](PLAN-profiles.md) owns that mechanism.
When profile selection reaches `hire`, it must reuse the profile key and config
directories rather than inventing a second account path.

## 6. Discovery and the guide

The window carries `OFFICE_TOOLS=office`. It is static for the image's lifetime;
terminal peer membership, which can change, is discovered through `office peers`
rather than copied into the environment.

`/workdir/<agent>/AGENTS.md` and `/workdir/<agent>/CLAUDE.md` contain the same
short guide, and `AGENT_GUIDE` points at the former for CLIs that need an
explicit path. The agent's own name and the tenant lead are baked in; the lead
is stable tenant state, while the changing peer set is not. The guide tells it
to use `office peers`, `office send`, and the pulled board verbs; it contains no
peer list that could go stale.

| CLI | How it finds the guide |
|---|---|
| Claude Code | `CLAUDE.md` in the working directory |
| Codex | `AGENTS.md` in the working directory |
| agy | the explicit `AGENT_GUIDE` path |

The two files are deliberately duplicated. An `@AGENTS.md` include in
`CLAUDE.md` creates a per-project approval gate in Claude Code; duplicating a
small guide is cheaper than leaving a headless agent at that prompt.

Only the lead's guide adds the assignment rule: check `office status`, hold work
from a `blocked` agent, and do not try to fix it. This is a pull by the lead, not
a watchdog message. Watchdog alerts go to a human through the alerts API and
never arrive as an envelope to any agent; messaging the lead would invite an
automated repair and could erase the silence that made a stall visible.

Claude Code's trust state is per working directory, so it cannot be baked into
the image for dynamically hired agents. Window creation writes
`hasTrustDialogAccepted` and `hasCompletedProjectOnboarding` for the new
`/workdir/<agent>` path. Without that, the roster and router say an agent is
live while its CLI is waiting at a first-run question.
