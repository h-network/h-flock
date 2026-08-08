# Build 09 — one `office` command

> Replaces `sendMessage`, `sendBroadcast`, `peers`, `hire`, `letGo`, `pause`,
> `resume` with subcommands of one binary.
>
> **Base on `main`.** Branch `bus/build-09-office-cli`, push to origin.

## 1. Why — found by running a real agent

An authenticated Claude Code was hired into a window and told to reply using
`sendMessage`. It used **Claude Code's own built-in `SendMessage` tool** — for
spawning sub-agents — and reported:

> `No agent named 'alice' is reachable. There are no spawned teammates in this
> session.`

A coherent-sounding failure from entirely the wrong subsystem. And the collision
surface is wider than one name — the same agent listed its tools as *"messaging
(SendMessage), tasks (TaskList/TaskGet/…), crons, MCP resources"*, so a future
`tasks` command lands in the same trap.

**A prefix fixes the class, not the instance.** Checked: nothing provides
`office`, and the CLIs' tool names are PascalCase, so a lowercase shell command
cannot be mistaken for one.

## 2. The surface

```bash
office send -a backend some text here    # to one agent
office broadcast some text here          # to every agent
office peers                             # who is here
office hire dave --cli claude            # enrol
office letGo dave                        # retire
office pause dave                        # stop the CLI, keep everything
office resume dave                       # start it again, drain the inbox
office --help                            # the whole surface, one place
```

Still focused commands — each has its own `--help` and none requires knowing a
kind, a payload shape or a queue. What the single binary buys beyond the
collision fix is **one discovery point**: an agent that finds `office --help`
finds everything.

⚠ **`office send` must take its message literally.** Today `sendMessage -a bob
run: sendMessage -a alice hi` fails — argparse eats the inner `-a`. An agent
telling another agent how to run a command is the *normal* case, so the message
is `nargs=REMAINDER` or everything after the recipient, and never re-parsed.

⚠ **`--help` must work with no environment**, as the current tools already do.

## 3. Every subcommand is a send or a read

This is what makes it one module rather than a dispatcher across two:

| | becomes |
|---|---|
| `send` | one `Message` envelope |
| `broadcast` | N `Message` envelopes — roster VAB `tmux`, minus self |
| `peers` | a roster read |
| `hire` / `letGo` | a `StartAgent` / `StopAgent` envelope **to `host`** |
| `pause` / `resume` | a `PauseAgent` / `ResumeAgent` envelope **to `host`** |

So `flock.office` imports **`flock.bus` only** — no cross-module import, and
`CONTRACTS` §1 holds unchanged.

⚠ **This is a behaviour change worth doing deliberately.** `hire` currently calls
the `flock.control` opener *directly*, so a hire from a window never reaches the
router, while the same operation over HTTP does. Sending an envelope unifies the
two paths: one route, one set of log records, and the control openers reached
only through the bus — exactly as `POST /agents/host/envelopes` already does.

Consequence: `office hire` becomes fire-and-forget like everything else on the
bus. It returns a `stream_id`, not a result. That is correct — `LLD-api` §3 says
the same of the api — but it means "did it work" is answered by `office peers`
or the log, not by an exit code.

## 4. What goes away

- `flock.adapter.tools` — `sendMessage`, `sendBroadcast`, `peers`
- `flock.control.cli` — `hire`, `letGo`, `pause`, `resume`
- all seven `[project.scripts]` entries

`flock.control`'s **openers stay** — they are how the kinds are handled at the
far edge. Only its CLI goes.

`OFFICE_TOOLS` becomes `office`, and the guide points at `office --help`.

## 5. Done when

- `office --help` with an empty environment lists every subcommand
- `office send -a backend run: office send -a alice hi` delivers the text intact,
  inner flags and all
- `office hire dave` produces a `StartAgent` envelope in the log addressed to
  `host` — not a direct opener call
- `office peers` prints agents only, no VABs, no self
- none of the seven old commands remain on `PATH`

## 6. Reporting

`jira done`, then message `architect` with paths, the subcommand list, and status.
