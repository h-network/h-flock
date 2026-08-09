# Build 16 — the profile link, and `cloneToAll`

> Two independent pieces, two lanes, no shared files. Both were designed in
> [`SPRINTS-next.md`](SPRINTS-next.md) §4 and §2 and neither is blocked.
>
> **Base on `main`.** Branch `<lane>/build-16-<piece>`, push to origin.

---

# A. The profile link — `tmux`

## A1. What is broken

`setup.sh` asks for accounts, the entrypoint seeds a config dir per account, and
`StartAgent` stores a `profile` key per agent. Then nothing reads it.

`flock.tmuxhost` reads the `launch` key to know which CLI to start and **ignores
`profile` entirely**, so every agent runs against the default config dir.
**Accounts are seeded, selected, and never used** — the feature looks present and
does nothing, which is worse than its absence.

## A2. The change

When creating a window, read the agent's `profile` key. If set, put these in the
window's environment beside `AGENT_NAME`:

```
CLAUDE_CONFIG_DIR=/home/ubuntu/.claude-<profile>
CODEX_HOME=/home/ubuntu/.codex-<profile>
```

⚠ **Both, always, regardless of which CLI is launching.** An agent may be
`letGo` and re-hired with a different CLI, and the window environment is fixed at
creation. Setting only the one that matches today's CLI leaves a window that
breaks on re-hire for reasons nobody will connect to this line.

⚠ **No `profile` key means set neither** — not empty strings. An empty
`CLAUDE_CONFIG_DIR` is not the same as an unset one, and the CLIs treat it
differently. Absent means "use the default", which is the current behaviour and
must stay exactly that.

⚠ **Do not create the directories here.** The entrypoint seeds them
(`seed_profile_dir`), including the first-run keys. A window that creates an
empty config dir gets an agent that meets the onboarding gates we spent build 15
removing.

⚠ **agy has no per-profile config dir** and is not part of this. It keeps one
OAuth token at a fixed path, so profile-per-account does not apply to it. Say so
in `PLAN-profiles.md` rather than inventing a third variable.

## A3. Done when

- an agent hired with a profile has both variables in its window environment
- an agent hired without one has neither variable set at all
- the directories are the entrypoint's, not created by window creation
- `PLAN-profiles.md` records that agy is outside this mechanism

---

# B. `cloneToAll` — `bus`

## B1. What it is

One repo into every agent's home, so a team starts from the same checkout:

```bash
office cloneToAll git@github.com:h-network/h-flock.git
office cloneToAll <url> -a alice,bob        # a subset
office cloneToAll <url> --dry-run           # show and stop
```

Each agent gets an **independent clone** at `/workdir/<agent>/<repo>` — own
branches, own index, own remote. Not a shared directory.

## B2. Fetch once, clone locally — keep this

The first agent is cloned **from the network**. Every other agent is cloned
**from that first local copy**, which git does with hardlinks: near-instant, and
the objects cross the network once rather than N times.

⚠ **A local clone points `origin` at the local path.** Reset it to the upstream
URL after each one, or the second agent's `git push` writes into the first
agent's directory. This is the whole trick and also its one sharp edge.

⚠ **Skip an agent that already has the directory**, do not overwrite. Re-running
after hiring someone new should fill the gap and touch nobody else's work. A
half-finished clone must be removed rather than left.

## B3. Which agents

From the roster, filtered to **VAB `tmux`**. An app client has no home directory
and `host` is not an agent; both would fail confusingly.

⚠ `flock.office` imports `flock.bus` only, and this needs nothing more — roster
membership and VAB are already there.

## B4. It writes other agents' directories, deliberately

Every other cross-agent operation sends an envelope. This one does not, and that
is a conscious exception rather than an oversight:

- a clone is **inert**. It creates files; it does not instruct anybody. The rule
  it would otherwise break exists to stop one agent *acting on behalf of*
  another, and putting a repo on disk is not that
- it is **idempotent and visible** — the directory is either there or it is not
- routing it as an envelope would give every agent its own network fetch, losing
  the only interesting property in §B2

⚠ **This does not generalise.** If a second "write another agent's home"
operation ever comes up, it does not get to cite this one — it argues its own
case or it becomes a kind.

## B5. Done when

- `--dry-run` lists every tmux agent with `would clone` / `exists, would skip`
  and writes nothing
- a real run clones once from the network and the rest locally
- **every** clone's `origin` is the upstream URL, not a local path — check the
  second and third, not only the first
- an agent that already has the directory is skipped, and re-running is a no-op
- app clients and `host` are not attempted
- a failed clone leaves no partial directory
- the summary line says how many cloned, skipped, failed

---

## Reporting

`jira done`, then message `architect` with paths, the surface you built, and
status. ⚠ These two touch no common file — if you find yourself editing the other
lane's, stop and say so.
