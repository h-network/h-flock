# Build 14 — paste timing, and the codex / agy first-run gates

> Claude is already handled: three seeded config keys in
> [`container/Dockerfile`](../container/Dockerfile) turn its first-run gates off
> before an agent ever meets them. codex and agy are not, and both have gates
> that stop a window dead while looking perfectly healthy.
>
> **Base on `main`.** Branch `tmux/build-14-cli-hardening`, push to origin.

## 1. `PASTE_ENTER_DELAY` → `0.5`

One line in `src/flock/tmux/ops.py`. Keep the environment override; change the
default and the comment.

The current `0.15` came from h-office's field experience and it works for
Claude — this is not a bug report. It is a margin decision. Comparable numbers
measured elsewhere for the same CLIs sit far above ours: a 0.3s baseline, 2.0s
for Claude Code's Ink renderer, 1.5s for agy. Ours is the outlier by an order of
magnitude, and the failure mode is the worst kind — **the Enter is swallowed, the
message sits unsubmitted in the input box, and the agent looks idle forever**.
Nothing errors and nothing logs.

⚠ **The cost of raising it is bounded and the cost of it being too low is not.**
Half a second per delivery against a delivery that already takes ~500 ms; versus
a message that is silently never seen. If ~500 ms of added latency ever matters,
that is a reason to revisit the number, not to have picked the smaller one now.

## 2. codex — the launch flags

`startAgent` comes from the `h-network/base` image and is **shared with
h-office**, so do not edit it there. Add what codex needs where h-flock already
handles Claude: a seeded config in this image.

Seed `/home/ubuntu/.codex/config.toml` with:

```toml
check_for_update_on_startup = false
```

⚠ **This one is not cosmetic.** codex shows an "Update available!" dialog at
startup whose first menu option — the default — runs `npm install -g
@openai/codex`. That is a **global** install inside our container: it would swap
the codex binary underneath every other agent in the tenant while they are
running. A stray Enter is all it takes. Suppressing the check is the fix; nobody
should be relying on a dialog nobody reads.

⚠ **Merge, do not overwrite**, exactly as the Claude seeding does — a
`config.toml` arriving later via `container/home` must keep its own keys. It is
TOML, so this is not a `json.load` one-liner; a small Python block that reads,
sets, writes is fine, and creating the file when absent is the common case.

Two other flags are worth knowing about but are **out of scope** because they
belong to `startAgent` in the base image, not here: `--no-alt-screen` (keeps
output inline so scrollback holds history, which our session socket would
benefit from) and `--disable shell_snapshot`. Note them in your report; if they
are worth having, they are a base-image change and a separate conversation.

## 3. codex and agy — the gates we cannot pre-empt

Both CLIs have a workspace-trust prompt on first launch in a new directory, and
**neither is covered by the permission-skip flag**:

| CLI | gate | how it clears |
|---|---|---|
| codex | "allow Codex to work in this folder" / "Do you trust the contents of this directory?" | Enter |
| agy | "Yes, I trust this folder" picker, Yes pre-selected | Enter |
| agy | "How's the CLI experience so far?" survey | `0` then Enter |
| codex | "Sign in with ChatGPT" first-run auth menu | **a human, or nothing** |

⚠ **Do not build screen detection for these.** Pattern-matching a TUI to decide
what state it is in is a large, per-CLI, per-version commitment, and h-flock has
deliberately never read a pane to make a decision. This section is
**documentation, not implementation** — write it into
[`PLAN-profiles.md`](PLAN-profiles.md) so the next person who tries codex or agy
recognises the symptom instead of debugging the bus.

⚠ **The symptom is what matters:** the window is alive, the process is running,
the output renders correctly, and the agent never responds to anything. It looks
exactly like a hung bus. It is not.

If a config key exists that pre-empts either trust prompt, seeding it is
in scope and better than everything above — **but do not invent one.** A key
that does nothing is worse than a documented gate, because it reads as solved.
Report what you find either way.

## 4. agy is not safe to orchestrate yet — write it down

agy's approval dialogs and pickers **consume pasted text as the answer to the
dialog**. Our adapter pastes as soon as the busy tag clears and has no idea a
picker is up, so a teammate's message would be read as a menu selection.

⚠ **That is worse than a lost message — it is a wrong action taken on the
agent's behalf, silently.** A dropped message is visible in the log; a menu item
chosen by an unrelated sentence is not.

No fix in this build: the honest one needs exactly the screen detection §3 rules
out. Record it in [`TODO.md`](TODO.md) as a known limitation with the reason, so
"add agy to an office" is a decision someone makes with this in front of them.

## 5. Done when

- `PASTE_ENTER_DELAY` defaults to `0.5`, override still honoured, comment says
  why the number moved
- a fresh container has `/home/ubuntu/.codex/config.toml` with
  `check_for_update_on_startup = false`, owned by `ubuntu`
- an existing `config.toml` keeps its other keys
- `PLAN-profiles.md` lists the four gates and their symptom
- `TODO.md` carries the agy paste hazard
- 122 tests still green

## 6. Reporting

`jira done`, then message `architect` with paths, status, and — separately —
**anything you found about a trust-prompt config key**, since that would change
§3 from documentation into a fix.
