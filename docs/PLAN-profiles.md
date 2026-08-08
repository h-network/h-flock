# Plan — CLI profiles and multiple accounts

> Not scheduled. This is the shape, taken from h-office's `field-feedback`
> branch, which solved it in production. Nothing here is built.

## 1. The problem, and the unit that solves it

Agents need to run under **different accounts**. One agent per account does not
work: a config dir is one interactive login, so a dir per agent means a browser
flow per seat.

h-office's answer, and the sentence worth keeping:

> **The unit is the account, not the agent.** A config dir is one interactive
> login, so one dir per agent would mean a browser flow per seat. Several agents
> share a profile, and the profile named `default` is the stock `~/.claude`, so
> only the extra accounts cost a login.

So: **profiles are a level above agents.** Many agents → one profile. `default`
is free.

## 2. How a profile is selected

Two environment variables, read by the CLIs themselves — nothing of ours parses
them:

| CLI | Variable | Points at |
|---|---|---|
| `claude` | `CLAUDE_CONFIG_DIR` | `~/.claude-<profile>` |
| `codex` | `CODEX_HOME` | `~/.codex-<profile>` |

Set them in the window's environment and the CLI picks up that account. That is
the whole mechanism. **`startAgent` needs no change** — it reads `AGENT_CLI` and
`exec`s, inheriting whatever the window was given.

## 3. What a fresh profile dir needs

A new dir is not an empty dir — an unseeded one costs the agent every office
default. h-office copies from the stock profile:

```
  CLAUDE_CONFIG_DIR  ←  ~/.claude   settings.json, skills, agents, CLAUDE.md
  CODEX_HOME         ←  ~/.codex    config.toml, AGENTS.md
```

Copy only what is missing, so an agent that already has its own keeps it.

⚠ **And a `.claude.json` written *inside* the profile dir**, minimally:

```json
{ "hasCompletedOnboarding": true }
```

`$HOME/.claude.json` covers the **default profile only**. Our current Dockerfile
seeds exactly that one — so the moment a second profile exists, its first
`startAgent` lands on the theme picker again. This is the bug h-office fixed in
`4b88096`, and we would reintroduce it.

Written minimally rather than copied, deliberately: the real file accumulates
project history, `userID` and `machineID` — session state a separate account is
meant not to inherit. Preferences that matter, theme included, are in
`settings.json`, which *is* copied.

## 4. Where the mapping lives

h-office's rule, which we already follow for the roster: **env is what persists,
everything else is derived.** They carry `AGENT_PROFILE_MAP` and `AGENT_CLI_MAP`
as container env and re-bake them on every start, because their entrypoint
regenerates the roster and would otherwise erase the declaration.

For h-flock:

- **`AGENT_PROFILES=alice:work,bob:work,carol:default`** alongside `AGENTS`, seeded
  the same way. Defaults-plus-exceptions, not a question per agent — h-office
  notes eleven agents became four answers rather than twenty-two.
- **The CLI per agent already has a home**: the `launch` key that `StartAgent`
  writes and `flock.tmuxhost` now reads. Profile should go the same way rather
  than inventing a second mechanism.
- `flock.tmuxhost` adds `CLAUDE_CONFIG_DIR`/`CODEX_HOME` to the window env it
  already builds, next to `AGENT_NAME` and `AGENT_PEERS`.

## 5. Two traps h-office hit, both worth avoiding by construction

**Pointing an agent at a local model stripped its account.** Their `llm.py`
replaced an agent's whole `env:` block, so switching to a local model removed
`CLAUDE_CONFIG_DIR`, and switching back removed it again. Fix: a setter owns only
the keys it is responsible for — `ANTHROPIC_*` — and never rewrites the block.

We have no local-model path yet. When one arrives, this is the failure to design
out rather than debug.

**Credentials permissions.** They widened a `chmod` to cover `.claude-*` and
`.codex-*`; a profile dir is as sensitive as the default one.

## 6. What this unblocks

This is the second item in [`TODO.md`](TODO.md)'s agent chain — credentials —
answered properly rather than with a single mounted file. With profiles, "how do
agents authenticate" becomes "which account is this agent on", and the answer
persists across rebuilds instead of being redone by hand.

It also makes the third item, the `startAgent` flip, safe to do: every window
starts a CLI that has an account and has already been through onboarding.

⚠ Still needs a decision that is not ours to guess: **where the credentials
themselves come from.** Seeding copies settings, not logins. Each non-`default`
profile still costs one interactive login, done once and then persisted — which
means the profile dirs have to survive a container rebuild, i.e. a volume. That
is the piece h-office gets for free by being long-lived, and we do not.
