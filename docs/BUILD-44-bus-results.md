# Build 44 — bus documentation consistency results

Worked from commit `564089f4dc8711832b84d7d117b8c2725305b335`.

## Documents compared

The owned documents `LLD-bus-and-switch.md` and `CONTRACTS.md` were each checked
against themselves, `HLD.md`, each other, and the seams documented by the API,
session, tmux port, tmux host, container, watchdog, and public API documents.

## Description contradictions corrected

- `LLD-bus-and-switch.md` described many tenants sharing one Redis and called
  per-agent isolation structural. The same document's security boundary says
  agents are trusted colleagues with loopback Redis access, while
  `LLD-container.md` specifies one tenant and one Redis per container. The LLD
  now describes the deployed topology and presents per-agent ACLs only as a
  policy the key shape could express later.
- `LLD-bus-and-switch.md` said every terminal agent inherits `REDIS_URL`.
  `LLD-container.md` says that variable is removed before tmux starts. The LLD
  now distinguishes removal of credential-bearing environment from the
  agent's continued ability to reach loopback Redis at its known default.
- `LLD-bus-and-switch.md` said `prefix()` applies to every key. Other documents
  also describe tmux/session files and environment keys. The invariant now says
  every Redis key, which is the scope the function actually governs.
- `CONTRACTS.md` omitted `all` and all-digit values from the prefix validation
  contract, contradicting `LLD-bus-and-switch.md`'s addressing rules. The
  contract now includes both rejections.
- `CONTRACTS.md` gave the old two-argument `generate_agents_md` signature,
  contradicting the three-argument signature in `LLD-tmux-host.md`. It now
  includes optional `lead`.
- `CONTRACTS.md` said logs exist only on daemon stdout. The bus LLD, HLD, and
  container LLD describe the window spool and board action record. The contract
  now distinguishes daemon stdout, the window spool, and `TASK_RECORD`.
- `CONTRACTS.md` required `stream_id` on every log record, contradicting its own
  lifecycle examples and `LLD-container.md`. It is now required on envelope
  events and absent on lifecycle records.
- `CONTRACTS.md` said `ResumeAgent` drains an inbox, while `LLD-port-tmux.md`
  says it only kicks delivery. The operation now says it kicks queued ingress.
- `CONTRACTS.md` said stopping an API client purges all per-agent state, while
  `LLD-api.md` says its inbox and data survive retirement. Both affected
  contract passages now say classified identity state is purged and retained
  data survives.
- `CONTRACTS.md` put the roster row before launch/profile/endpoint state on
  `StartAgent`, contradicting `LLD-tmux-host.md`'s race-prevention ordering. The
  prose and sequence now put desired launch state before the roster trigger.
- `CONTRACTS.md` still said roster ownership was deferred. Its own control
  contract defines runtime enrollment and retirement. The roster section now
  names container boot seeding and control runtime ownership.
- `CONTRACTS.md` response examples omitted current agent fields and fixed API
  and host participants. They now match the response shapes documented by
  `LLD-api.md`.
- `CONTRACTS.md` said the whole container inherited every shared variable and
  counted three `ROSTER_POLL_SECONDS` readers. `LLD-container.md` documents
  selective handoff, and the port is kick-and-exit. The environment contract
  now names the two pollers and the variables deliberately withheld from agent
  windows.

## Design contradiction — deliberately not corrected

- `LLD-bus-and-switch.md` line 171 says a gateway routes between tenants, and
  its participant table reserves `gateway` as a VAB. Lines 847–852 instead say
  cross-tenant routing is not a separate component but a switch branch that
  learns remote Redis addresses and writes their stores. Recommendation:
  architect and operator must choose. A gateway participant preserves local
  switch scope and puts remote topology at an addressed boundary; a switch
  branch centralizes resolution but gives each switch remote topology and
  credentials. The conflicting text remains unchanged.

## Contradictions in documents owned by other lanes — not edited

- `HLD.md` lines 130–133 say “Nothing writes another agent's keys.” Lines
  392–395 correctly qualify this as “No AGENT” and name the switch ingress and
  `AddTicket` board writes. Recommendation: qualify the earlier description in
  the same way.
- `LLD-api.md` lines 123–128, `LLD-port-tmux.md` line 160, and `HLD.md` lines
  251–255 equate no activity history with unknown presence. `LLD-watchdog.md`
  line 110 distinguishes a fresh healthy agent whose delivery judgment is
  unjudged. Recommendation: reserve unknown for presence and say that missing
  activity history makes delivery judgment unjudged.
- `LLD-container.md` lines 171–174 count the tmux port as a
  `ROSTER_POLL_SECONDS` reader. The port LLD specifies a kick-and-exit
  process; only switch and tmuxhost poll. Recommendation: remove the port
  from that sentence.
- `LLD-container.md` lines 191–193 promise that restart re-attaches to existing
  correct state, while lines 219–220 explicitly accept losing Redis queues on
  restart. Recommendation: this is a design decision, not a wording repair.
  Choose whether tenant restart is allowed to discard custody state or whether
  Redis durability is part of restart convergence; persistence costs storage
  lifecycle and recovery policy, while disposable Redis preserves the simpler
  tenant model but cannot promise backlog survival.
