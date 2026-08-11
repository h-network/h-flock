# Parked

Things decided-but-not-done, so they live somewhere other than a chat log.

## Open right now

⚠ **`clients/` is finished.** The Telegram bot and the browser console stay as
**demos** — two working examples someone can run on day one. No further client
development happens in this repository; the framework is the product.

| | |
|---|---|
| **profile logins** | one interactive login per account. Not buildable — a person has to do it. ⚠ **Checked: nobody has solved this.** NVIDIA OpenShell's own tutorial says you authenticate with your own account in a browser, and trust the workspace when prompted |
| **local model: long-context behaviour unknown** | every test was a short turn against a 65k window. Nothing says what a local agent does when it fills |
| **security: what is left after build 36** | ⚠ **The boundaries are done** — TLS on both doors with a refusal to serve a non-loopback bind without it, `producer` stamped from its egress queue, and a tenant that will not start with a widened Redis bind and no password. What remains is **CORS and per-client tokens** on the api door. ⚠ **Nothing here isolates agents from each other**, deliberately: h-flock is a development office, agents are colleagues who were hired. HMAC envelopes, a brokered `office`, one OS user per window — that is a service executing work for callers it does not trust, a different product |
| **the console cannot reach TLS doors** ⚠ *found by testing TLS, not by reading* | `clients/web/server.py` proxies for the browser, and its own client is plaintext-only: the WebSocket proxy opens a bare `socket.create_connection` (so terminals break against **any** cert, valid or not), and the REST proxy uses the default verifying context with no CA or insecure option. ⚠ **A supported configuration that breaks the shipped demo is a defect, not a missing feature** — but `clients/` is closed to development, so this is recorded rather than fixed. Roughly 30 lines in one file: ssl-wrap the socket, pass a context, add the option. Until then TLS belongs in a reverse proxy in front of loopback-published doors (`LLD-container` §3) |
| **an alert you can clear** ⚠ *asked for by the operator* | Alerts are an append-only stream with no acknowledgement. Clearing must be keyed by **cursor** — one instance — so it can never become "mute this kind". Spec: `BUILD-38-durable` §1 |
| **credential alerts never clear** | Measured: `status=absent` raised at `01:00:42Z`, login completed at `01:07Z`, nothing ever retracted it, so the console correctly rendered a fact that had been false for an hour. ⚠ **It was only ever tested firing.** `BUILD-38-durable` §2 |
| **the permission mode lives only in argv** | A hired agent starts as `claude --dangerously-skip-permissions …` (verified at +4s/+8s/+12s) and was later seen as bare `claude` carrying `CLAUDE_CODE_RELAUNCH_*`: the CLI re-executed itself and the flag went with it, leaving the agent asking for permission. ⚠ **The trigger is unknown** — a forced resize does not reproduce it. `BUILD-38-durable` §3 |
| **console conversation needs `--audit-log`** | Outbound messages are rebuilt from the audit log, so without that flag every refresh looks like data loss. Agent replies survive; yours do not. `BUILD-38-durable` §4, and a failing flow in `clients/web/flow-check.py` |
| **no acceptance seat** | Everything above was found by an operator, not by a lane or by me. Lanes have no Docker and cannot run what they build; the architect writes the specs and then checks his own work. ⚠ **`flow-check.py` is the floor, not the answer** — a script catches regressions, it does not notice an agent quietly asking for permission |
| **ollama — untested, not judged** | the installer asks, falls back to `/api/tags`, and reports what `/v1/messages` answered — but none of that path has been run against an actual ollama. ⚠ **This entry used to assert that ollama needs a translating proxy in front. That was never measured and has been removed** — reasoning presented as a finding is the thing this file exists to prevent. What is known: claude talks to `/v1/messages`, vLLM serves it, and nobody here has asked ollama |

⚠ **macOS, 2026-08-11:** installs and runs on a stock MacBook (Apple Silicon,
Docker Desktop) — plumbing check 25/25, simulator 19/19. `setup.sh` used
`declare -A`, which is a syntax error on the bash 3.2 macOS ships, so it died on
its first prompt; the maps are now bash-3 compatible. LibreSSL 3.3.6 accepts
`-addext`, so the self-signed path works there too.

⚠ **TLS run end to end, 2026-08-11:** a tenant with a real certificate serves
TLS 1.3 on both doors and passes the plumbing check 25/25, and the failure
simulator 19/19. Two defects only that run could find: the healthcheck probed
plain HTTP at an HTTPS door, so a working TLS tenant sat unhealthy forever; and
both checker scripts had the scheme baked in as a constant.

⚠ **The "TLS breaks sim-blocked" item is closed, and it was never about TLS.**
`sim-blocked.sh` sourced `container/.env` over an exported `TENANT`, so running
it against any tenant other than the one in that file polled the wrong tmux
session. The ready poll saw no window and failed; the gone poll saw no window
and passed — which is exactly the flaky, paired signature that made it look
environmental. `tmux` answered `can't find session: hq` on every call, into a
stream nothing was reading. **The same bug was fixed in `plumbing-check.sh` days
earlier and missed here**, and the lesson is that one: a fix to a shared pattern
is not done until every copy of the pattern has it.

⚠ **Verified by running it, 2026-08-11:** plumbing check 25/25 and the failure
simulator 19/19 against a real tenant, after a from-scratch image build. The
same run found that build 36's TLS guard refused every container (a bind is not
an exposure — `LLD-container` §3.1), and two defects in the check itself: it
hardcoded session `hq`, and sourcing `container/.env` overwrote an exported
`POD`/`TENANT`, so its documented override checked the wrong tenant.

**Recently closed:** the installer's TLS answer (build 37 — create, copy, start; host path is not the container path), macOS support, the terminals view ignoring a hire, port security on `producer` and TLS on both doors (build 36 — each forced on the lab, not reasoned about), the stranded window (a `__init__` placeholder holds the
session open now), silent trust and guide failures (recorded, still never
raising), the console audit scope (renamed to Operator Action Log), the terminal view (the console has a full workspace), the
five doc drifts (audit 06), AddTicket delivery without a window (build 35),
credential staleness (a decision, not a fix),
credential alerting, `delivery_unjudged`, and the octal/snapshot/telemetry
defects a night of live running turned up.

⚠ **This index has been wrong four times in one day.** Each time a build closed
an item and nobody told this file — the correction arrived in a later audit
rather than with the work. **A build that closes an item marks it in the same
commit.** Do not leave it for a sweep.

## Everything below is closed

⚠ **A struck-through or `SHIPPED` heading is a record of the time it was
written**, kept because the reasoning is why the fix went the way it did. Those
sections name commands that no longer exist — `sendMessage`, `sendBroadcast`,
`peers` — and that is deliberate: they are what the problem looked like then. The
current surface is one `office` command (`CONTRACTS` §5). Everything **not**
struck through is present tense and should be true today.

Each says *why* it is parked — an item with no reason is either work or noise.

Deferred *design* questions stay in each LLD's §7. This is the operational list.

## Agents in windows

⚠ **This was wrong, and build 15 disproved it by testing rather than reading.**
Both have seedable state: codex trusts a directory via `[projects."<cwd>"]
trust_level = "trusted"` in `config.toml`, and agy is suppressed entirely by
`cache/onboarding.json`. Both are seeded now and both CLIs start unattended.

The original entry, kept because the reasoning is why it went unchecked so long:

**Onboarding for `codex` and `agy` — checked, and there is nothing to seed.**
Run headless in a fresh container, both go **straight to a login prompt**:
codex offers "Sign in with ChatGPT / Device Code / API key", agy offers "Google
OAuth / Cloud project". Neither has a pre-login gate.

`claude` is the odd one out — a theme picker *and* a per-directory trust dialog
before login, which is why it alone needed `hasCompletedOnboarding` and
`hasTrustDialogAccepted` seeded.

Their post-login approval gates are already covered: `startAgent` passes
`--dangerously-bypass-approvals-and-sandbox` to codex and
`--dangerously-skip-permissions` to agy.

So all three need only **credentials**, which
[`container/seed-home.sh`](../container/seed-home.sh) now handles.

**A delivery arriving while a modal is open is lost — every CLI, not just agy.**

Measured on 2026-08-09 against a live tenant. A `/model` picker was opened in an
agy window and a normal `office send` was delivered into it:

- **the message vanished** — no trace in 2000 lines of scrollback, no reply to
  the sender, and the bus logged `opened` and considered it delivered
- **the Enter selected the highlighted row.** Benign here, because the highlight
  sat on the current model. It need not have been

⚠ **Originally filed as an agy problem, and that was too narrow.** agy surfaces
it often because its pickers are everywhere, but the mechanism — a modal has
focus, so the paste goes nowhere and the Enter actions the modal — is true of
claude and codex too. Any CLI, any modal.

⚠ **`Escape` before pasting was tested and rejected. Do not re-propose it.**
It does close a picker, and a message delivered straight after one landed
correctly. But sending it to an agent that is *mid-generation* **aborts the
work** — verified: the pane showed `Interrupted · What should Antigravity CLI do
instead?`. Delivering to a busy agent is the normal case and a picker collision
is rare, so the mitigation destroys real work far more often than it saves a
message. The trade runs the wrong way.

⚠ **Built in build 19, and it does not catch this case.** Measured: with a modal
open the message was consumed and never seen, yet claude wrote `input` records
anyway, so verify passed it. Verify catches an unsubmitted paste, not a modal
swallow. The modal hole is still open.

→ **What would actually help is `verify`** — confirm the text landed after
delivering, and re-deliver when it did not. Already parked above as the missing
step h-office added after measuring ~1 delivery in 10 left unsubmitted. It
catches the silent loss. It does **not** prevent the stray menu selection, and
nothing short of reading the screen before every paste would.

**Credentials and profiles — mechanism SHIPPED, logins outstanding.**
`container/seed-home.sh in|out|check` copies keys and credentials into a running
tenant and saves logins back out, and `setup.sh` asks for accounts and seeds each
one's config dirs. What remains is doing the interactive logins once.

⚠ **Last link missing:** nothing reads the `profile` key yet. `flock.tmuxhost`
reads `launch` for the CLI but does not turn `profile` into `CLAUDE_CONFIG_DIR` /
`CODEX_HOME` in the window environment — so accounts are seeded and selected but
not used.

The shape was taken from h-office, which solved it. The unit is the *account*, not the agent: a config dir is one
interactive login, so several agents share a profile and `default` is free.
`CLAUDE_CONFIG_DIR` / `CODEX_HOME` in the window env is the whole mechanism.

⚠ Our current onboarding seed writes `$HOME/.claude.json`, which covers the
**default profile only** — a second profile lands on the theme picker again
unless its own dir is seeded. Same bug h-office fixed in `4b88096`.

⚠ Still undecided: profile dirs must survive a rebuild, so they need a volume.
h-office gets that for free by being long-lived; we do not.

**The `startAgent` flip — and it was never about bash.** Found by watching a real
agent reply: `flock.tmux.create_window` launches the CLI **bare** —
`env AGENT_NAME=backend claude` — instead of `startAgent claude`. So the
permission flags are never applied and every command the agent runs stops on
*"This command requires approval"*.

`startAgent`'s own header says why that wrapper exists: *"Each CLI spells 'don't
stop to ask me' differently — claude `--dangerously-skip-permissions`, agy the
same, codex `--dangerously-bypass-approvals-and-sandbox`. Remembering which
belongs to which is the whole reason this wrapper exists."*

→ launch `startAgent <cli>` rather than `<cli>`. One line, and it covers all
three CLIs by construction rather than us tracking three sets of flags.

**The old framing.** Windows still run `bash -il`. `create_window` already
takes a command and `StartAgent` already passes one, so this is a default, not
work. Held deliberately until the two items above are solved — flipping first
just means every window stops on a prompt.

**Agent guide naming the lead is written once at window creation.**
If the lead is retired or re-ordered, existing agents' guides still name the previous lead until their windows are recreated. This is accepted because lead changes are rare, re-writing every guide on every roster change introduces unnecessary moving parts, and `office peers` reads the `<prefix>:lead` key live.

## Delivery

**~~The `verify` step~~ — SHIPPED in build 19.** Measured: 0 false positives
over 6 landed deliveries, and it catches the Enter-not-taken case below.

⚠ **The "misses a modal swallow" claim that stood here has been deleted**, along
with the same claim in `HLD` §8 — it came from a test asserting an absence that
passed whenever the router had not yet judged. A modal was never separately
measured, so this file now claims nothing in either direction.

**Retry decision — CLOSED in build 30: surface, do not re-paste.** An unverified
verdict cannot tell an unsubmitted paste from one queued inside a stopped CLI or
picker. The simulator confirms the first text remains in both detected cases;
retrying while blocked cannot help, and retrying after a human clears it can
execute the instruction twice. We chose possible loss over possible duplication:
retain `blocked`, alert the human, and put the no-retry reason in the structured
`delivery_unverified` record. A human can resend when duplication is known safe.

The original entry, for the reasoning: `LLD-adapter-tmux` §4 says "verify,
optionally" and we took the option. h-office enables it by default after *"roughly one delivery in
ten left its message sitting in the recipient's input box, marked delivered and
already popped off the queue"*. That is a silent loss path: `opened` is logged,
the envelope is gone from Redis, and the message was never submitted.
→ check the bottom rows for the message's tail after Enter, press it again if
still there. Costs one extra Enter that an empty prompt ignores.

## ~~An unknown agent reads as "exists, idle"~~ — SHIPPED in build 25

`404` for a name not in the roster, `200` for an enrolled agent holding nothing,
and `all` exempt because it is the broadcast address rather than a member. The
reasoning below is why it sat open as long as it did.

`GET /agents/<name>` returns **`200` with zero depths** for a name that is not
enrolled, and `404` only when the name breaks the segment rule. So a client
cannot tell "no such agent" from "an agent with an empty queue" — the two answers
are byte-identical.

Found by the api lane while verifying every call for [`API.md`](API.md), which is
the value of documenting against a running system rather than against the code.

⚠ **It is a trap for an app**, which will happily send to a typo'd name forever:
the `POST` is accepted, the envelope dead-letters somewhere the client never
sees, and the depths read zero throughout. Every layer answers truthfully and the
sum is misleading.

→ **Parked, not fixed**, because the fix is a decision rather than a patch:
`404` on an unenrolled name is the obvious answer, but the same handler serves
`host` and `api`, and boards deliberately return `200`/`[]` for an agent holding
nothing (`LLD-api` §2). Changing one without the other trades this inconsistency
for a worse one. Documented accurately in `API.md` in the meantime.

## ~~Visibility~~ — SHIPPED in build 20

**Presence** is `working` / `idle` / `unknown` on `GET /agents/{agent}` and in
`office status`, derived from the activity feed. **`blocked`** followed in build
28, from the router's own delivery verdict. The **watchdog** shipped in build 27
and alerts a human, never an agent.

⚠ ~~One class remains open~~ — **closed in build 31, and it was never real.**
The claim was that a CLI at a login prompt records input it never acts on, so
verification passes. It came from a test asserting an *absence*, which passed
whenever the router had not yet judged. With the verdict waited for
deterministically, claude and codex are **both caught**. Nothing here needs a
screen.

The original entry: **Presence.** No busy / idle / wedged / login-expired signal. h-office calls it
*"the single most expensive gap in a long session"* — every state looks
identical from outside. The signal is `window_activity` from one `list-windows`
call, which `LLD-adapter-tmux` §5 already names.

**Watchdog — both halves of the signal now exist.** It was blocked on boards, and
boards shipped in build 11. A ticket in `doing` carries `started_ts`, so "took
work and has not finished it" is answerable; window silence is the other half and
stops it crying wolf at an agent that is thinking. Nothing else blocks it.

**~~Boards~~ — SHIPPED in build 11.** Tickets, four columns, `office add`/`list`/`take`/`done`/`cancel`/`hold`/`delete`,
and an append-only history in `$TASK_RECORD`. The rule the design turned on held
all the way through: **the agent moves its own tasks, nothing infers them** — the
adapter knows an envelope was delivered and cannot know whether the agent read
it, started it, or disagreed with it.

⚠ It went further than that in the end: **nothing delivers a ticket at all.** A
board is pulled, so the one-`doing` rule is not enforced, it simply falls out.
The watchdog's evidence — a ticket sitting in `doing` with a `started_ts` — now
exists.

## ~~Broadcast strands envelopes on the fixed agents~~ — SHIPPED

**Fixed in build 08.** An unroutable VAB now dead-letters instead of returning
before popping, and VAB `api` has a delivery routine. `sendBroadcast` also
resolves its own recipients, so agent broadcasts never reach the fixed agents at
all. ⚠ Still undecided: whether `POST /agents/all/envelopes` *should* reach them
— an architect loose end, now cosmetic rather than a leak.

<details><summary>original</summary>

**Found by an agent during the first live run, then confirmed: `api` ingress was
34 and climbing, `host` dead-letters were 34.** Every `send all` reaches both,
because the router fans out to `_agents() - {sender}` and the fixed agents are
roster rows like any other.

`host` handles it correctly — VAB `control`, no opener for `Message`,
dead-lettered and logged. Noisy, but visible.

`api` does not. VAB `api` dispatches to no delivery routine, so
`flock.adapter.runner` logs `VAB is 'api', not 'tmux'` and **returns before
popping**. The envelope is never consumed and never dead-lettered: it just
accumulates, one per broadcast, forever.

Two faults meeting, and they can be fixed independently:

1. **No `api` delivery routine.** The api-adapter opener — an envelope handed to
   a waiting HTTP client (`LLD-api` §7). Its absence should not be silent
   accumulation.
2. **An unroutable VAB should dead-letter, not return.** Whatever else is true,
   an adapter that cannot deliver must leave the envelope visible, the way an
   unknown `kind` already does. §4: *nothing disappears silently.*
3. **Whether broadcast should reach the fixed agents at all is still undecided.**
   The old router excluded `api`; the current one includes it. Neither is written
   down — this is an architect loose end, noted at the time and not closed.

</details>

## ~~What belongs in a window's environment~~ — SHIPPED

**Done in build 08.** `AGENT_PEERS` removed, `OFFICE_TOOLS` added, the guide
names only the agent and is written once. Rule kept below because it decides
every future variable.

**The rule: static for the window's lifetime → environment. Derived from the
roster → a tool, never environment.**

A window's environment is frozen at creation. So anything that changes while the
office runs is wrong there, and goes stale silently.

| | |
|---|---|
| `AGENT_NAME` | env — fixed for this window |
| `POD`, `TENANT` | env — what `send` needs, fixed |
| `OFFICE_TOOLS=send,peers,…` | env — ships with the image, cannot go stale |
| **peers** | **a tool.** Changes the moment `StartAgent` adds one |

⚠ **`AGENT_PEERS` (build 06) breaks this and should be removed.** Add networking and
backend's `AGENT_PEERS` is wrong until her window is recreated — the exact
staleness the roster exists to prevent.

⚠ **The guide has the same bug.** `write_agent_guide` runs at window creation
only, so `/workdir/<agent>/AGENTS.md` ages the same way. Fix both together:
`flock.tmuxhost` already reconciles every `ROSTER_POLL_SECONDS` and already reads
the roster, so **rewrite the guide each pass**. A few hundred bytes, and it
leaves one source of truth instead of two that drift.

`OFFICE_TOOLS` also covers the reader who stops early: `echo $OFFICE_TOOLS` then
`--help` on each, with no exploring and no source to read.

## ~~Log records from agent tools never reach the log~~ — SHIPPED in build 20

`office` writes to a file the router tails into stdout, so `sent` reaches the
log. **A delivered envelope leaves five records, not four.**

The original entry: ⚠ **`office` runs in an agent's window, so its log records go
to that pane** —
not to the container's stdout, which is the only thing collected.

Measured: an envelope sent by an agent produces `popped`, `forwarded`,
`received`, `opened` centrally. **`sent` is missing.**

⚠ **Half solved in build 11, and the half that is solved shows which option
works.** Board events no longer go through `log_record` at all — they append to
`$TASK_RECORD`, a shared file the container collects, written by one function
(`flock.bus.record_task_event`) that swallows every error so a bad log path
cannot fail a `done`. That is the second of the three options below, chosen in
practice rather than in principle.

**Still open: `sent`.** `office send` from a window still logs to that pane. The
same fix would work; it has not been done, and the reason boards went first is
that the watchdog needed them.

Two documented claims are therefore false as written:

- `LLD-bus-and-router` §4 — *"four records across a delivered envelope's life"*.
  ⚠ **Corrected in build 20: it is five**, and the four was arithmetic that only
  looked right because the missing one was the one nobody could see.
  True for api-sent envelopes; agent-sent ones have three centrally and one in a
  terminal. The crash-detectability argument does not cover the agent's end.
- the board plan claimed *"there is no second place to look"*. Was true and is
  now fixed: `$TASK_RECORD` is that one place for board events.

The design assumed every emitter is a container process. An agent's tools are
not, and nothing about `flock.bus.log_record` writing to stdout is wrong — it is
that stdout means something different in a window.

→ Options, none chosen: emit to a Redis list the container tails; write to a
shared file the container collects; or accept it and correct the two claims.
⚠ Do not "fix" it by having agents' tools skip logging — the record is useful in
the pane too, as the agent's own confirmation.

## Found by running a real agent

First live test with an authenticated Claude Code in a window. Delivery worked —
the envelope reached the TUI, was read, and acted on. Three findings:

⚠ **1 is fixed** — `create_window` writes the guide and trust for every caller,
and build 17 gave both paths one `window_env`. 2 and 3 below still stand.

**1. `hire` never writes the guide or the trust entry.** Two code paths create
windows: `flock.tmuxhost.create_window` writes the guide, the `CLAUDE.md` copy
and the `.claude.json` trust entry — and the **control opener calls
`flock.tmux.create_window` directly**, skipping all of it. A hired agent gets an
empty `/workdir/<name>` and a trust prompt it cannot answer headlessly.

→ Move guide-and-trust writing into `flock.tmux.create_window` itself, so both
callers get it. One implementation, two callers, which is why that library
exists.

⚠ It looked fine earlier only because the guide was rewritten on every reconcile
pass. Removing that loop was correct and exposed a gap that was always there.

**2. ⚠ `sendMessage` collides with Claude Code's own built-in tool.** Told to
reply, the agent used its native `SendMessage` — for spawning sub-agents — and
reported *"No agent named 'backend' is reachable. There are no spawned teammates in
this session."* A coherent-sounding failure from entirely the wrong subsystem.

The name is not neutral inside the CLI we run. Worth reconsidering: `officeSend`,
`msg`, or something with no built-in of the same name.

**3. An agent with no guide reaches for tools, not commands.** Told to run
`peers`, it searched its *tool list* and concluded none existed — it never
considered a binary on `PATH`. Which is correct behaviour with no context, and it
means the guide is doing more work than "being nice": it is what tells an agent
that this office is driven by shell commands at all.

## The agent-facing surface

**Principle: anything reachable will be explored, and a confusing sanctioned path
guarantees it.** Observed: an agent asked to find its peers hit
`AGENTS=backend:tmux,...` — the container's seed string, with VABs in it and itself
included — and went to `redis-cli` for a better answer, arriving at the roster
hash with `api` and `host` in it. It did nothing wrong. The best answer available
was one it should never have seen.

Two halves, and they only work together:

**Give them clean tools — SHIPPED.** `sendMessage`, `sendBroadcast`, `peers`
all live, `--help` works with an empty environment, generic `send` gone from
`PATH`. The plan named:
`sendMessage`, `sendBroadcast`, `peers`, `hire`, `letGo`, discovered via
`OFFICE_TOOLS`. One general `send --kind … --payload '<json>'` was wrong because
it makes an agent learn the envelope model to use it at all.

⚠ Concrete instance already open: **`send --help` fails without `AGENT_NAME`** —
it checks the environment before parsing arguments, so the first thing anyone
types errors out. Help must never depend on the environment.

**Take the unsanctioned path away — except we cannot, and that is decided.**
Agents keep `sudo`: the container grants `ubuntu` `(ALL) NOPASSWD: ALL`, and that
is wanted (possibly per-agent optional later). ⚠ **So nothing inside the container
is a boundary.** Not file modes, not a compiled binary, not Redis ACLs — `sudo
cat redis.conf` and `sudo redis-cli` end all three. The container is the boundary;
inside it, everything is visible.

That changes the Redis ACL item below from a security control to a tidiness one,
and it means source-hiding should be **deterrence, not enforcement**:

- **Delete `/app` from the final image.** The source is copied there to build and
  the package installs into `/opt/flock`; nothing needs it at runtime. This
  removes the stumble rather than labelling it, and costs nothing.
- **A banner at the top of anything they may still reach** — and it must give a
  *reason*, not a prohibition. These agents reason around bare rules: one read a
  comment in `pyproject.toml` and turned it into a finding. "This is bus
  internals; `send --help` is your interface, and queue names here will change"
  answers the question they were about to ask. A bare "do not read" is an
  invitation.
- Use the convention they already respect — the `AGENTS.md` style — rather than
  inventing a new marker.

**Write it at the top.** Agents stop reading early. Whatever matters most goes
first: who you are, who you can talk to, how to send. Anything below the fold is
effectively absent, so the guide staying *short* is a feature — every paragraph
added pushes something out of the part that gets read.

## ~~Authority between agents~~ — SHIPPED in build 21

The lead is the first name in `AGENTS`, recorded at boot, named in every agent's
guide and marked by `office peers`. Build 26 added `office status` and told the
lead to check it before assigning — and **not** to try to fix an agent.

The original entry: **Agents have no model of who has standing, and correctly
refuse to take direction.** Observed in the first live discussion run: asked why it had not
followed a peer's instruction, an agent answered *"frontend isn't my principal — you
are. His messages reach me the same way any data does."* That is right, not a
malfunction — the bus proves **who** sent a message and says nothing about **who
may direct whom**, and nothing in an agent's context supplies it.

Build 06 tells each agent its **peers** — and "peer" is precisely a relationship
with no authority in it, so they talk and nothing moves.

Naming is unsettled and is the open question here. `AGENTS.md` in this office
uses **lead**; the ask was phrased as an **architect** title. Not the same thing:
one is a role in a hierarchy, the other is a named job. Decide before building.

Also unsettled: what standing actually means to an agent. "Act on this rather
than consider it" is the useful half; "believe anything that claims to be from
them" is the failure mode next to it.

⚠ **Blocked on the item below.** Telling an agent that requests from a named
peer carry authority makes `producer` load-bearing, and `producer` is currently
forgeable — see next. Ship the standing model on top of an unenforced identity
and any agent can impersonate the lead and direct the whole office.

## A live terminal view in the web client — wanted, not built

*"Show me what's happening live"* — the raw pane, not the activity feed.

⚠ **The capability already exists**: `flock.session` on `:8081` streams a
`capture-pane` snapshot then live `%output`, and takes keystrokes back with
`read-only` enforced server-side. Nothing new is needed in the framework.

What is missing is the client half:

- **the browser, not Telegram.** Terminal bytes are ANSI escapes and redraws;
  they render with xterm.js and are noise in a chat message
- **the proxy must bridge a WebSocket too** — the same CORS and
  `EventSource`-cannot-set-headers problems apply to `:8081`
- **render it, never parse it.** This is the sanctioned use of that door and the
  exception invariant 7 names: a person may read a terminal, the system may not

⚠ **Do not let a terminal view become a data source.** The moment a client reads
an answer off the pane instead of the mailbox, every CLI version bump becomes our
problem — which is the thing the whole activity/verify design exists to avoid.

## Security — all parked deliberately

**TLS.** Both doors are plain HTTP on `0.0.0.0`, so the bearer token crosses the
network in the clear. Terminate outside the process (`LLD-api` §7); a proxy in
front of both doors is where it goes (`LLD-container` §3).

**CORS.** No headers, so a browser app from another origin is blocked at
preflight — and it looks like the api being down rather than a header missing.
One middleware, once an origin is known.

⚠ **Corrected: `REDIS_URL` is *not* in agent windows.** Build 08 took it out —
measured on a live tenant, an agent's environment has no `REDIS_URL` at all, and
`office` reaches Redis through `flock.bus`'s own default rather than a variable
handed to the window. It was removed after an agent asked where its peers were,
found the variable, and went to `redis-cli` for the answer.

⚠ **But the ability is unchanged.** Measured in the same tenant:
`redis-cli -h 127.0.0.1 DBSIZE` → `24`. Redis listens on loopback with no auth,
`redis-cli` is on `PATH`, and the default URL is a fact about a tenant rather
than a secret. **Removing the variable removed the signpost, not the door** —
which is exactly what the design claims to do and no more.

So ACLs remain the only thing that would actually *prevent* it, and the entry
below still stands on its conclusion even though its reason was wrong.

**Redis ACLs.** The original entry read: `REDIS_URL` is in every agent window
because `send` needs it, so an agent can bypass both doors and write any
queue directly. Invariant 3 is a convention `send` honours, not something
enforced.

⚠ **Demonstrated, not theorised.** From inside an agent window, an `RPUSH`
straight into a *peer's* ingress with `"producer": "architect"` was accepted by
Redis. Invariant 2 — *the sender comes from the queue the envelope was popped
from* — holds only for envelopes that reach the router via egress. **A direct
ingress write bypasses the router entirely and forges identity.**

That makes this the gate on the authority model above, and on `producer`-based
policy for control kinds. `LLD-bus-and-router` §3.1 anticipated the fix: a
credential scoped to `~pod:<pod>:tenant:<tenant>:agent:<agent>:*`, which is why
the agent sits in the address at all.

**`producer` policy on control kinds.** Any agent can enrol or kill any other
today. An allow-list in the control opener is the right place — but only once
`producer` is genuinely unforgeable, which it is not while any window can write
a peer's ingress directly.

## ~~Correlation~~ — ANSWERED in build 12

**Ephemeral named agents won**, not the expiring table. A client enrols itself
with `vab: api`, gets an address and a mailbox, and the bus demultiplexes by
address — so no table keyed by `correlation_id` exists anywhere, which was the
point of preferring that shape.

⚠ **It is still not a reply on the same request.** `POST` returns `202` as it
always did; the answer arrives in the client's mailbox and is read by cursor or
SSE. Request/response was never the shape — an agent takes seconds to minutes to
answer, and holding an HTTP request open for that is the thing the design avoids.

**Still open: per-client tokens.** One shared token, and `as` is checked against
the roster rather than proven.
