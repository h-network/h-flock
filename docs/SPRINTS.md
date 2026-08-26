# Sprints

[`TODO.md`](TODO.md) says *what* is open. This says *in what order, with what
else, and against which test run*.

A sprint here is not a theme. It is a batch that satisfies three constraints at
once:

1. **One file cluster**, so one lane owns it and one review covers it.
2. **One test run proves it** — if two rows need different hosts or different
   evidence, they are different sprints.
3. **It fits in a merge.** Two sprints in flight, never three. An idle lane
   costs less than a wrong merge.

⚠ **Rows are claims about the tree, and they rot.** Every citation below was
re-checked on 2026-08-23. Re-check before you start: this file was written from
a tree that has since moved. The last reconciliation found **five** rows
describing work already done, and the citation gate could not catch one of them
— every path they named still existed.

⚠ **A sprint that closes a row marks it closed in the same commit.** Not in a
later sweep. `TODO.md` has been wrong four times in one day for exactly this.

---

## ~~Sprint 1 — the `office` command tells the truth~~ — SHIPPED as build 87

⚠ **Merged 2026-08-23 at `1212fa7`**, verified by `tmux` (author NO), and confirmed
live on h-lab by an acceptance run that exercises the three unquoted `office
send` calls in `plumbing-check.sh` (`BUILD-89-results`). All three rows closed.
**The agent guide changed in the same merge** — it was still teaching the form
the new parser rejects.

**Rows:** *`office send` cannot carry a real payload* · *`--agent=NAME` is
rejected with a message that does not say why* · *command naming is
inconsistent*
**Files:** `src/flock/office/cli.py` — one file.

| | |
|---|---|
| payload | `--stdin` and `--file`; refuse when mixed with positional text; refuse empty stdin, because a pipe that produced nothing must not arrive as a blank message |
| acknowledgement | `send` returns a bare stream id, which confirms *enqueueing* and nothing else. It must carry **recipient and bytes accepted** |
| equals form | `src/flock/office/cli.py:110` checks `argv[0] not in ("-a", "--agent")`, which cannot see the `--agent=bob` that argparse accepts everywhere else |
| aliases | `let-go` and `clone-to-all`, keeping `letGo` and `cloneToAll` |

⚠ **The first three are one change, not three.** `src/flock/office/cli.py:104`
is `nargs=argparse.REMAINDER`, which is why a mistyped flag becomes message text
*and* why line 110 exists as a hand-rolled substitute for parsing. Remove the
cause and both symptoms go.

⚠ **The risk is the same line.** Dropping REMAINDER changes parsing for every
`send` in the repository, and `src/flock/office/cli.py:125` has a second one.
**Write the test that sends a body containing `--flags` first**, then change the
parser — otherwise the regression is invisible until an agent hits it, which is
how this row was found in the first place.

**Test run proves:** an agent with a multi-line report sends it and the whole
report arrives. Today it sends the single word `--stdin` through six clean
custody stages.

---

## ~~Sprint 2 — control says what it did~~ — SHIPPED as build 91

⚠ **Merged 2026-08-23 at `463df5d`**, verified by `bus` (author NO) **after five
refusals — four of them against the architect's contract, not the code.** The
rule that came out of it is general and is in `BUILD-91` ruling 11: *acknowledged
is a fact, UNKNOWN is an attempt with no reply, `failed` is reserved for not
attempted or provably rejected.* ⚠ **It then found five more sites outside this
build**, two of which could make the custody log report a delivery loss that
never happened — see `TODO.md`. ⚠ **The hire row is only HALF closed**: control
records what it *accepted*, and whether the window actually appeared is
`tmuxhost`'s to say.

**Rows:** *a hire leaves no record of whether it worked* · *`--profile` is not
validated against the accounts that exist* · the watchdog half of
*`CLAUDE_CODE_OAUTH_TOKEN`*
**Files:** `src/flock/control/openers.py`, `src/flock/watchdog/service.py`.

| | |
|---|---|
| confirmation | `src/flock/control/openers.py` contains **no emit call at all**. `StartAgent`, `StopAgent`, `PauseAgent` and `ResumeAgent` take custody and never say what they did. `src/flock/port/openers.py:211` already does this right — `board_write_confirmed` is the pattern to copy |
| profile | an invalid `--profile` dead-letters with a bare `KeyError` repr, naming neither the problem nor the rule, one component away from where it was typed. A *plausible* typo is worse: it passes, the directory gets seeded, and the agent starts cleanly against an account nobody configured |
| credentials | `src/flock/watchdog/service.py:264` tests for `.credentials.json`, so an agent authenticated by token alerts `absent` **forever** — and credential alerts never clear |

**Test run proves:** hire an agent and learn from the log alone whether it
worked. Today the only way to find out is to attach to a pane.

---

## ~~Sprint 3 — cost is either right or says it isn't~~ — SHIPPED as build 88

⚠ **Merged 2026-08-23 at `60ba4dd`**, verified by `tmux` (author NO) after a
refusal that found three real defects. ⚠ **Two halves remain and have their own
`TODO.md` rows**: `rate_limits` has never run against a live codex agent, and
`office status` still says `unknown` for agy in the column beside the one that
was fixed. The agy claim itself is proven live against a real hired agent.

**Rows:** *presence and cost are not comparable across CLIs* · the open half of
*nothing says what a run costs* · two findings from the 2026-08-23 live run
**Files:** `src/flock/watchdog/activity.py`, the `office usage` renderer,
`tests/fixtures/`.

| | |
|---|---|
| codex model | `src/flock/watchdog/activity.py:154` falls through to `"unknown"`, so every codex row prices as `unpriced` — indistinguishable from a genuinely free local model. ⚠ **The model is in `turn_context`**, emitted once per turn as `payload.model`, not in the usage record. Take the last one at or before the record's ordinal, so a mid-session model change is followed |
| agy | agy records **no token counts anywhere**. Its state is SQLite and protobuf, not JSONL; the model is there (`gemini-3.7-flash`, one row per generation) and the counts are not. **So agy is not priceable from local state**, and the fix is to say so in the output rather than to write an adapter that cannot exist |
| rate limits | codex logs `used_percent`, `resets_at` and `plan_type` beside every usage record. We surface none of it, and it is the limit an operator actually hits |
| attribution | decide whether a trimmed marker gets a signal, **or close the row**. `src/flock/port/openers.py:69` bounds markers at 500 and the comment above it argues the loss should stay silent — a counter that fired on the normal case was built and deleted in review once already |

⚠ **Fixtures are the deliverable, not a side effect.** Both defects above
shipped because a test constructed a shape the vendor has never written and
passed — the extractor and the fixture agreed with each other and both
disagreed with reality. Every fixture this sprint adds is **trimmed from a
captured session file**, and the test says where the sample came from.

⚠ **`last_token_usage`, never `total`.** `total` is cumulative: on one real
session the first record read 14,132 for both and the last read 3,332,258
against 111,751. They are identical in the first record, which is precisely why
a one-record fixture cannot catch it.

**Test run proves:** this one is verifiable **offline** against captured files.
Confirm live afterwards.

---

## ~~Sprint 9 — finish what today half-finished~~ — SHIPPED 2026-08-24

⚠ **Both merged: build 102 (`bus`, verified by `api`) and build 103 (`tmux`,
verified by `bus`). 513 tests.**

⚠⚠ **The two builds interlocked, and that is the result worth keeping.** `bus`
spent 102 proving desired-state writes are non-atomic and leave residue. `tmux`
added a new piece of state to that exact sequence in 103. Then `bus`, as
verifier, **reproduced** the consequence rather than arguing it: an incomplete
`StartAgent` stranded `window.cause`, and a later window would `GETDEL` it and
attribute itself to a hire that never completed. **Neither lane failed. The
sprint caught it because the two halves were scheduled together.**

⚠ **And the fix generalised backwards.** `tmux` solved it with neither of the two
options the architect offered — not cleanup, not a flipped order — but by making
the dangerous state **unobservable**: roster `HSET` before cause `SET` inside one
Lua call, because **Redis Lua cannot roll back, so the ORDER decides which
partial can exist.** That reading then produced a third, cheaper answer to 102's
own atomicity question, now on `TODO.md`: `stop_agent` removes the roster first
and purges after, so **reversing it turns an invisible corruption into a visible
one, for free.**

⚠ **What 102 established, which nobody knew:** a half-removed agent does not look
broken — it **vanishes**, because the roster row is the part that got removed.
Re-hiring the same name **succeeds**, inheriting a `paused` or `blocked` marker
and a held `delivering` lock, so its mail cannot be delivered. It also produced
**the first live `_incomplete` in this repository's history** — the shape five
refusals designed, outside a unit test for the first time.

### The original plan

⚠ **Two builds, because with four lanes at most two may author if the other two
are to verify.** That, not merge contention, is the constraint.

⚠ **Both items use something built today**, which is why they come before
sprint 4's alerts: the fault-injection harness from build 100, and the
`window_created` signal the acceptance seat found while measuring a gap.

⚠⚠ **CORRECTION, made before assigning: both are BIGGER than this plan first
said, and the plan was wrong in the same way twice.** I wrote 9a as *point the
existing harness at it* and 9b as *thread an id through*. Checking the code
first — which is the discipline every lane has been held to today — neither is
mechanical:

- **build 100's harness wraps `rpush` only**, targets the **ingress** key, and
  attaches to the **switch** process. A control-plane fault needs different Redis
  verbs and a different target process. **Extending it is part of 9a's cost.**
- **`tmuxhost` has no `correlation_id` to thread.** It reconciles from Redis, and
  `start_agent` never persists one. 9b needs a **new piece of desired state**,
  with a lifecycle, and it must tolerate `window_created` events that have **no
  cause at all** — tmuxhost rebuilds missing windows with no control envelope
  behind them.

**Both are still worth doing and the sprint stands.** Recorded because a spec
that calls something small when it is not wastes the lane's day, and I have said
that to three lanes today.

### 9a — characterise a partial control failure, then decide about atomicity

**Lane: `bus`.** ⚠ **A SPIKE, NOT A FIX.** The question is what a half-completed
control operation actually leaves behind — and whether that is bad enough to
justify making desired-state writes atomic.

`stop_agent` writes three times and `start_agent` several, with no transaction.
Build 91 made the **record** truthful (`_incomplete`, naming the acknowledged
subset) **without making the failure impossible.** Nobody has seen what a real
one leaves.

**Build 100's harness can now produce one.** Inject a fault between the roster
`hdel` and the resource purge on a live tenant, then report:

- exactly what state survives — roster row, agent resources, delivery lock,
  window
- what `office status` and `office peers` say about that agent afterwards
- whether a subsequent `StartAgent` for the same name succeeds, fails, or
  produces something worse than either
- ⚠ **the `_incomplete` record itself, live** — it has never been produced
  outside a unit test, and this is the cheapest honest way to reach one

⚠ **Then argue whether atomicity is warranted**, with the damage in front of you
rather than imagined. The option is a Lua script, as `watchdog/activity.py`
already uses. **"Not worth it" is a legitimate and expected answer** — a
mid-sequence Redis failure is rare, and the record is already truthful. **Do not
write the Lua script in this build.**

### 9b — close the hire row properly: join `window_created` to its cause

**Lane: `tmux`.** Rows: *join `window_created` to the control record* and the
open half of *a hire leaves no record of whether it worked*.

⚠ **This row shrank on measurement rather than on argument.** It assumed
`tmuxhost` needed a new confirmation record. It does not —
`src/flock/tmuxhost/host.py:116` and `src/flock/tmuxhost/host.py:150` **already
emit `window_created`.** The only thing missing is a `correlation_id`, so nothing
can say *which hire produced which window*.

**Thread the id through.** Then `start_agent_accepted` and `window_created` join,
and the question *"did the hire work"* becomes answerable from the log — which is
what the original row asked for and build 91 could only half-deliver.

⚠ **Do NOT make control wait for it.** `tmux` argued this and was right: waiting
turns an asynchronous architecture into a gate, and window presence does not
prove correct configuration.

⚠ **The gap is 4.091 s, measured on a live tenant** (`BUILD-94-results`). Whatever
you build must tolerate it.

### Not in this sprint, and why

| | |
|---|---|
| **alerts** (sprint 4) | spec already written, genuinely ready — but neither item uses today's work, and it will still be ready next sprint |
| **acceptance never exercises `office usage` or `office status`** | a real gap and a third build; it needs a verifier and we have two |
| **the other failure shapes** | reachable now, and **each costs a live tenant.** 9a reaches one because it answers a question — do not chase the set |
| **`gateway` vs cross-tenant** | ⚠ **one decision, and it is the operator's.** Two rows sit still until it is made |

---

## Sprint 4 — alerts you can act on

**Rows:** *an alert you can clear* · *credential alerts never clear* · *console
conversation needs `--audit-log`*
**Spec:** already written — `BUILD-38-durable.md` §1, §2, §4.

Clearing is keyed by **cursor**, one instance, so it can never become "mute this
kind". Credential alerts were only ever tested firing: one was raised at
`01:00:42Z`, the login completed at `01:07Z`, and nothing ever retracted it — so
the console correctly rendered a fact that had been false for an hour.

⚠ **The console half skips silently without a playwright venv**, which is how
acceptance ran green for weeks without ever exercising it. See
`BUILD-CONVENTION.md` §3.0b.
⚠ **`--audit-log` touches `clients/`, which is closed to development.** It is a
flag rather than a feature, so it is in scope — but say so out loud when it
lands, or the next reader will think the freeze broke.

---

## Sprint 5 — broadcast, and the six-record contract

**Rows:** the broadcast half of *envelopes have no TTL or hop count* · *the
six-record contract has holes under load*
**Files:** `src/flock/bus/doors.py`, `src/flock/switch/`.

| | |
|---|---|
| broadcast | `src/flock/bus/doors.py:60` skips the policy check when the destination is `all`, so the ACL covers every send except the one that fans out. A broadcast storm has nothing in front of it |
| contract | re-measure. The recorded rates predate v3, v4 and `send_refused`, so nobody knows whether the rewrite already fixed them |

⚠ **This sprint got cheaper on 2026-08-23.** It carried a third row — reworking
the `[message from x]` pane presentation — which was **decided against**: the
sender is already a header field, the string is one line in one opener, and it
is a published contract in both the api docs and the agent guide. See `TODO.md`.

⚠ **That decision is also what unblocks the measurement.** Every delivery test
counts by grepping `[message from x]`, so changing it would have rewritten the
instrument this sprint measures with, forcing an order inside the sprint. Not
changing it means the contract can be re-measured against the suite as it
stands.

⚠ **The only sprint that needs the performance host.** Fold *local model:
long-context behaviour unknown* into the same trip — nothing says what a local
agent does when it fills its window, and that needs the same machine.

---

## ~~Sprint 6 — the door for callers we don't trust~~ — CLOSED, no build

**Rows:** the remainder of *security: what is left after build 36*
**Files:** none — no api-lane work follows from this.

⚠ **DECIDED 2026-08-26** (`docs/TODO.md`, "security: what is left after build
36"): **not building CORS or per-client tokens.** The trust boundary is the
container, not identity inside it — access control that doesn't match that
model is false security, not defense in depth. Audit logging (the custody
chain) is the honest tool for this trust model; access control is not.

⚠ **Nothing new is needed to make that true.** Direct `flock.api` traffic —
the one shared bearer token, `as` validated only against roster membership —
is already traced through the custody chain: bus/port stdout logs and
`GET /agents/{agent}/activity` (`LLD-api.md:172`). The row closes on the
existing mechanism, not a new one.

The narrow version of *signed envelopes* — per-client keys at the door — is
withdrawn along with it, for the same reason: it was the access-control
answer to the gap this decision says isn't being closed that way. Intra-tenant
signatures still buy nothing regardless — any key an agent can sign with it
can also read, same user, same box. Cross-tenant remains the first real
boundary and is still blocked on the `gateway`/switch-branch decision below.

---

## Sprint 7 — coordination between agents

**Rows:** *the task board has no push* · *an agent cannot tell what its peers
are* · *`correlation_id` is invisible to agents*

Everything here was asked for by the agents themselves after a live multi-party
run, which is the reason to trust the list.

| | |
|---|---|
| board | a ticket lands with **no notification**, so the guide instructs a manual doorbell after every assignment and a lead hand-counts message budgets. Assignment should deliver itself |
| peers | `office peers` returns names. Nothing says which framework a peer runs — and the three differ in what they can do, what they can be pointed at, and whether they can be priced at all |
| threads | the fabric mints and propagates `correlation_id` through every custody stage; it is the join key the whole custody log is built on. `office send` neither shows it nor accepts one, so a thread is reconstructible from the log and not from the interface an agent uses |

---

## Sprint 8 — operating a tenant over time

**Rows:** *`office swap <agent> --cli <x>`* · the live half of *seeded
credentials do not survive `--force-recreate`* · the precedence half of
*`CLAUDE_CODE_OAUTH_TOKEN`* · *the framework cannot see the SSH access its
agents depend on*

`swap` needs no new machinery — the CLI is a Redis value and the host already
rebuilds a missing window from it. The open questions are behavioural: drain or
discard the ingress, what presence reads during the gap, and what happens to a
ticket already in `doing`. ⚠ **Not stop-then-start** — that destroys an api
client's unread mailbox.

⚠ **agy has no per-profile support anywhere**, so a tenant gets **one agy
account** however many are configured, and nothing says so at setup. That is a
sentence, not a feature.

⚠ **Precedence is one test and one sentence**: when a profile has both a token
and a seeded credential file, which wins? It decides whether the help text says
*"paste a token"* or *"paste a token, and it replaces any login you seeded"*.

---

## The doc round — builds 92, 93, 94 — SHIPPED 2026-08-23

Cut from a documentation audit, then re-scoped when the audit showed the work
was not documentation.

| build | lane | verified by | outcome |
|---|---|---|---|
| 92 | `bus` | `tmux` | **merged** — one refusal: the broadcast reconciliation still folded an ambiguous forward into known loss |
| 93 | `api` | `tmux` | **merged** — two refusals, both a doc asserting what the code does not do |
| 94 | `acceptance` | — | `EXIT:0` plus a coverage map showing pause, resume and every failure shape have never run live |

⚠ **The audit's most useful output was that one item was not a doc task at all.**
`CONTRACTS.md` defined `send_failed` as *"was not written to egress"* — the
inference build 91 withdrew — while the **code** overclaimed identically. Fixing
the prose alone would have left a doc saying UNKNOWN over code emitting `failed`,
with the doc looking authoritative. It went into build 92 with the code.

⚠ **And the README carried a `README.md` example the merge had just broken.**
`office send -a frontend can you take a look at this?` — seven unquoted words,
rejected since build 87. Nobody opened the README before merging, including me.

---

## ⚠ Rows added after this plan was written

Today's builds and acceptance runs opened six rows that no sprint above covers.
**Re-slot them before picking sprint 4** — three of them are consequences of
sprint 2 and belong next to it, not at the bottom of a list:

- `tmuxhost` should emit the control confirmation — the half of *a hire leaves no
  record* that build 91 does **not** close
- control desired-state writes are not atomic, so a partial hire is possible
- a revoked OAuth token is invisible to the watchdog
- acceptance never exercises `office usage` or `office status`
- codex `rate_limits` has never been seen working live
- `office status` says `unknown` for an agy agent

---

## Parked, and why

| | |
|---|---|
| **profile logins** | a person has to sit at a browser. Not buildable |
| **the console cannot reach TLS doors** | real, ~30 lines, and `clients/` is closed to development. Recorded, not scheduled |
| **not ours: the model and the CLI** | listed so nobody hunts an h-flock bug when they see it |
| **the permission mode lives only in argv** | probably closed by the base image, and the original trigger was never reproduced, so there is nothing to test a fix against |
| **a naming review** | ⚠ **must come after sprints 1, 2 and 7**, or it reviews vocabulary that is about to move. See `BUILD-45-naming-inventory.md` and `BUILD-49-vocabulary.md` for what has already been inventoried |
| **a `gateway` participant** and **cross-tenant is designed twice** | ⚠ **one decision, not two rows, and it is the operator's.** Gateway-as-participant or switch-branch — only one can be built, and Sprint 6's cross-tenant half is blocked behind it |
| **no acceptance seat**, **every sign-off signed by its own author** | arrangements, not code. Recorded so they are chosen rather than drifted into, and h-flock sets an office up — it does not direct how agents work |

⚠ **The closed audit findings are in no sprint, deliberately.** A
finding is a claim until it is checked against the tree, and a previous auditor
on this project cited files that did not exist. **Triage is its own pass**, and
it should happen between sprints rather than inside one — two findings have
already been spot-confirmed as real, so it is not optional either.
