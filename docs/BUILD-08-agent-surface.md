# Build 08 — the agent-facing surface, and setup

> Four lanes, no overlap. Design is in
> [`PLAN-agent-tools.md`](PLAN-agent-tools.md), [`TODO.md`](TODO.md) and
> [`PLAN-profiles.md`](PLAN-profiles.md); this is the split and what done means.
>
> **Base on `main`.** Branch `<lane>/<what>`, push to origin.

## ⚠ Before any bare tmux command

```bash
export TMUX_TMPDIR=$(mktemp -d)
```

`flock.tmux.require_isolated_tmux` enforces this for anything going through
`run_tmux`. It has not stopped being possible to kill the office another way.

## 1. Why this sprint exists

Three agents were started with no deliberate context. One found `REDIS_URL` in
its environment, ran `redis-cli`, and mapped the whole infrastructure. The other
two read an env var and stopped. **What an agent knows is currently a function of
how curious it is.**

The fix is not a rule telling them not to look — it is having nothing to look
for. Clean tools, a current guide, and an environment that mentions no database.

## 2. `tmux` — the tools and the window

**Tools** (`PLAN-agent-tools.md` §2), each with real `--help`:

```bash
sendMessage -a bob some text here     # one agent
sendBroadcast some text here          # every agent, resolved here
peers                                 # who is in this office
```

- `sendBroadcast` **resolves its own recipients** — roster members with VAB
  `tmux`, minus the sender — and sends one `Message` each. It does **not** use
  `recipient: all`.
- `peers` is `HKEYS` + filter to `tmux` + drop self, via `flock.bus.roster`.
- ⚠ **No generic `send` on an agent's `PATH`.** Leaving one there reintroduces
  the discovery path this build removes. `--kind` stays as the library call.
- ⚠ **`--help` must never require the environment.** Today `send --help` fails
  without `AGENT_NAME`, which is the first thing anyone types.

**The window** (`TODO.md`, "what belongs in a window's environment"):

- **Remove `AGENT_PEERS`.** A window's environment is frozen at creation, so it
  is stale the moment `hire` adds someone.
- **Rewrite `/workdir/<agent>/AGENTS.md` on every reconcile pass**, not only at
  creation — same staleness, same fix, and `tmuxhost` already has the roster in
  hand every `ROSTER_POLL_SECONDS`.
- **Add `OFFICE_TOOLS=sendMessage,sendBroadcast,peers,hire,letGo`** — static for
  the image's lifetime, so it cannot go stale the way `AGENT_PEERS` did.

## 3. `bus` — `hire` and `letGo`

Thin commands over the `StartAgent` / `StopAgent` openers that already exist in
`flock.control`:

```bash
hire dave --cli claude
letGo dave
```

⚠ **Not `startAgent`.** The base image ships `startAgent`, which starts a CLI in
the *current* window. Ours enrols a *new agent*. Same name, opposite meaning,
both on `PATH`.

⚠ **No `--profile` yet.** It arrives with accounts (`PLAN-profiles.md`) and must
reuse that mechanism — do not invent a second way to choose an account.

## 4. `api` — stop stranding envelopes

The only thing on the list actively wrong in a running tenant. Found by an agent:
`api` ingress reached 34 and climbing while `host` correctly dead-lettered.

- **An unroutable VAB must dead-letter, not return before popping.** This is the
  general fault: `flock.adapter.runner` logs `VAB is 'api', not 'tmux'` and
  returns, so the envelope is never consumed and never dead-lettered. §4 says
  nothing disappears silently; this does.
- **Give VAB `api` a delivery routine** so it has somewhere to go rather than
  being unroutable. Discarding with a log record is a legitimate implementation
  for now — handing an envelope to a waiting HTTP client is deferred
  (`LLD-api` §7).

## 5. `architect` — setup, credentials, onboarding

**A host-side `setup.sh`**, modelled on h-office's. Asks, then writes
`container/.env` and brings the tenant up:

- pod and tenant name
- how many agents, and their names
- which CLI each runs — **defaults plus exceptions**, not a question per agent
- accounts: how many profiles, and which agents share which. `default` is the
  stock login and costs nothing; only extra accounts need a browser flow
- generates `API_TOKEN` if absent

⚠ **What is asked must survive a rebuild.** h-office's rule: *env is what
persists, everything else is derived.* Answers go to `container/.env`, the
entrypoint re-derives the roster from them at every start.

**Credentials** — h-office's pattern, not a volume: a `config/home/` directory on
the host holding ssh keys, `.gitconfig` and `.credentials.json`, `docker cp`'d in
after start, and copied back out after an interactive login so the next rebuild
already has it. Corrects `PLAN-profiles.md` §8, which says a volume is needed.

**Onboarding seeds for `codex` and `agy`** — existing ticket. `agy` is the
Antigravity CLI and keeps state under `~/.gemini/antigravity-cli`, with its own
OAuth token, so it is a third profile dir and not a passenger on the other two.

## 6. Done when

- an agent's environment is `AGENT_NAME`, `POD`, `TENANT`, `OFFICE_TOOLS` and
  nothing else of ours
- `peers` in alice's window prints `bob, carol` — no VABs, no self, no `api`/`host`
- `hire dave` gives dave a roster row, a home, a window and a CLI; `letGo dave`
  reverses it and he stays gone through two reconciles
- `sendBroadcast` reaches agents only, and `api` ingress stays at 0
- a broadcast to a VAB with no routine dead-letters with a reason instead of
  accumulating
- `setup.sh` brings a tenant up from answers alone, and a rebuild keeps them

## 7. Reporting

`jira done`, then message `architect` with paths, the contract, and status.

⚠ Do not edit another lane's files. If you need something in `flock.bus` or
`flock.tmux`, say so and I will freeze it first — that gap has cost us twice.
