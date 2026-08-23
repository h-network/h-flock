# Build 87 — `office send` carries a real payload, and says what it accepted

**Lane: `bus`. Base: `main` at `d313fbc`.** Branch from main, push to origin.

**Sprint 1 of [`SPRINTS.md`](SPRINTS.md).** One file:
`src/flock/office/cli.py`.

## Why, in one paragraph

A codex agent had a multi-line hardware report and ran
`office send -a architect --stdin`. The flag does not exist, `text` is
`argparse.REMAINDER`, so it was **not rejected — it became the body**, and the
agent sent the single word `--stdin`. ⚠ **Six clean custody stages carrying the
wrong content.** The send did not fail; it succeeded with the report missing, and
the acknowledgement — a bare stream id — confirmed enqueueing while saying
nothing about what was enqueued. Only a human reading the recipient's pane caught
it.

## What to build

| | |
|---|---|
| **`--stdin` and `--file PATH`** | body read from stdin or a file, so a payload is never shell-parsed |
| **refuse mixing** | `--stdin` together with positional text is an error, not a silent precedence rule. The agent has to learn which one it meant |
| **refuse empty stdin** | a pipe that produced nothing must not arrive as a blank message |
| **an acknowledgement that means something** | `send` must report **destination and bytes accepted**, not just a stream id |
| **`--agent=NAME`** | `src/flock/office/cli.py:110` tests `argv[0] not in ("-a", "--agent")`, which cannot see the equals form argparse accepts everywhere else |
| **kebab-case aliases** | `let-go` and `clone-to-all`, with `letGo` and `cloneToAll` still working |

## ⚠ The root cause is one line, and so is the risk

`src/flock/office/cli.py:104` is `nargs=argparse.REMAINDER`. That is why a
mistyped flag becomes message text **and** why line 110 exists as a hand-rolled
substitute for real parsing. Both symptoms die with the cause.

⚠ **There is a second REMAINDER at `src/flock/office/cli.py:125`.** Find out what
it serves before you change either.

⚠⚠ **WRITE THIS TEST FIRST, BEFORE TOUCHING THE PARSER:**

```
office send -a x "a body that contains --stdin and --file and -a inside it"
```

That must still arrive **whole and unaltered**. REMAINDER is what makes it work
today. Remove REMAINDER carelessly and argparse will eat those words as flags —
turning a message-mangling bug into a *different* message-mangling bug, which is
worse, because the first one is now documented and this one would not be.

⚠ **`--` as an end-of-flags separator is a legitimate part of the answer.** So is
requiring the body to be a single quoted argument. Choose deliberately and say
which in your sign-off; do not let argparse's default behaviour choose for you.

## Contract to state explicitly in your report

The exact accepted forms after this build, written as invocations. Every other
lane and the agent guide (`src/flock/tmux/ops.py:98` teaches agents how to
message each other) depends on knowing them, and `AGENTS.md` in each workspace
will need updating to match — **flag that, do not edit it yourself.**

## Done means

Pushed to origin. Tests green. `TEST-SIGNOFF` filled in, and ⚠ **`VERIFIED BY`
is not you** — this is the arrangement builds 80 to 82 established and it holds
here.
