# Build 76 — review our fabric against h-vab's design

> **Base on `main`.** Branch `bus/build-76-vab-review`, push to origin.
> Owner: `bus`. ⚠ **ANALYSIS ONLY — no product code, no renames, no refactors.**
> Deliverable is one document.

## 1. What to read, in this order

1. ⚠ **`docs/BUILD-46-vabtrial.md` and `docs/BUILD-46-bus-results.md` FIRST.**
   **You already ran this trial.** Build 46 put one path on the h-vab shape and
   reported eight concrete conflicts. Do not re-derive them — start from them and
   say which still hold after builds 47–75.
   ⚠ Note `BUILD-46-vabtrial.md` was damaged by the build-56 rename and repaired
   on 2026-08-15; `h-vab`, `adapter` and `router` in it are **h-vab's** vocabulary,
   not ours.
2. `git@github.com:h-network/h-vab.git`, branch `naming/vocabulary` —
   **`docs/FLOW.md`** then **`docs/NAMING.md`**. ⚠ **Nothing there is built.** It
   is a design with no implementation, which is the reverse of how we arrived.

## 2. Scope — the fabric only

**In:** `src/flock/bus/` and `src/flock/switch/service.py` — 1,029 lines.

**Out:** `tmux`, `tmuxhost`, `session`, `office`, `control`, `api`, `port`. h-vab
says nothing about panes, CLIs or boards, and their names were never the problem.

⚠ **Also out: `switch/activity.py`, `presence.py`, `verification.py`,
`windowlog.py`, `retention.py`.** They live under `switch/` but they are not the
fabric — see §3.

## 3. What we found on 2026-08-15 that already maps

Confirm, correct or reject each. **Where you disagree, say so** — these are my
readings from one pass, not findings.

| ours | h-vab |
|---|---|
| five observers run **inline on the forwarding thread**, one `try` around all five | **§8** — observer *"reads state ╳ never writes ╳ never in the forwarding path"* |
| a reach set combining forwarding + ACL in one lookup | **§9** `select_egress(source, destination)` → hit+permitted, or **dead-letter denied** |
| the kick is a **sole-path** doorbell; build 73 produced a frame in ingress no kick will ever collect | *"Why ⑪ cannot be the only path to the drain"* — level-triggered condition, doorbell as optimisation |
| `send_refused` vs `dead_lettered` | **reject vs dead-letter by DECIDABILITY**, not severity |
| the switch reads the whole 256-byte header, including `ttl`/`hops` it decrements | **§4 frozen read-set** — the switch reads `source`+`destination` only and *therefore cannot* enforce the hop limit; that belongs to the router |

## 4. The questions to answer

1. **Where do we already agree**, in behaviour rather than vocabulary?
2. **Where do we diverge, and is each divergence deliberate or accidental?**
   ⚠ Build 73's `ttl`/`hops` in the L2 header is the clearest candidate. I
   specified it. Say whether h-vab's tighter read-set is better and why.
3. **What does h-vab solve that we have not?** The terminal strand is the one I
   can see. Are there others?
4. **What do we have that h-vab does not account for?** Build 46 found eight.
   Which survive? ⚠ **This half matters as much as the first** — a design that
   cannot express something we need is a finding about h-vab.
5. **Which of our 67 measured comments** in those 1,029 lines encode something
   h-vab's design does not prevent? Those are the ones that must survive any
   rebuild, and re-deriving them costs what they cost the first time.

## 5. What NOT to do

- ⚠ **No code.** Not a spike, not a branch of the fabric, not a rename.
- ⚠ **Do not recommend adopting or rejecting h-vab.** That decision is Halil's.
  Give him the comparison he needs to make it.
- ⚠ **Do not treat h-vab as authoritative because it is written down.** It has no
  implementation and no measurements. We have 388 tests, proven conservation and
  a v4 wire verified byte-identical against real model output. **Where our
  measured behaviour contradicts their design, that is evidence, not error.**

## 6. Done when

`docs/BUILD-76-vab-review.md` exists on your branch and answers §4, with
`file:line` for our side and section references for theirs. `python3
tools/check_citations.py` clean.

`jira done`, then message `architect` with the five answers in a line each.

---

## 7. Review result

This comparison is between implemented h-flock at `677ee83` and h-vab design
commit `2fa36c2`. The asymmetry matters: h-flock's claims below are settled by
code and prior runs; h-vab's are design claims from `FLOW` and `NAMING`, with no
implementation or measurement behind them. This review therefore records
agreement, disagreement and missing coverage. It does not recommend adoption or
rejection.

The scope inventory in §2 is stale: the ten Python files under
`src/flock/bus/` plus `src/flock/switch/service.py` total **1,223 physical
lines**, not 1,029, at this base. The stated count of **67 comment lines** is
current and is reconciled in §12.

### 7.1 Corrections to the proposed mappings

| Proposed mapping | Verdict | Evidence |
|---|---|---|
| Five observers run inline on the forwarding thread under one `try` | **Confirmed, with a stronger divergence.** `Switch.run()` invokes all five before `step()`, under one exception boundary (`src/flock/switch/service.py:201-220`). At least retention and verification are maintenance actors, not read-only observers; calling all five observers understates the mismatch. h-vab `FLOW` §8 and `NAMING` §§8, 10 require observation outside forwarding, read-only, and never repairing. |
| Reach set combines forwarding and ACL | **Rejected.** The switch gets roster members (`src/flock/switch/service.py:38-39`) and makes an independent membership decision (`src/flock/switch/service.py:174-177`). Tag policy runs synchronously in `send()` (`src/flock/bus/doors.py:55-70`). There is no combined reach-and-permission lookup. h-vab `FLOW` §2 step 8 and `NAMING` §4 describe one `select_egress(source, destination)` decision, although the permission table's representation remains explicitly open. |
| Kick is the sole path to delivery | **Confirmed.** Every accepted unicast is kicked only after `forwarded` (`src/flock/switch/service.py:178-187`); accepted broadcast recipients follow the same pattern (`src/flock/switch/service.py:164-172`). There is no level-triggered drain in the scoped fabric. h-vab `FLOW` §2 steps 10-11 makes non-empty egress the condition and a doorbell only an optimisation. |
| `send_refused` versus `dead_lettered` follows decidability | **Confirmed for the normal boundary.** Address and policy failures are refused while the caller is present (`src/flock/bus/doors.py:55-79`); failures discovered after a switch or receive pop go to dead (`src/flock/switch/service.py:120-151`, `src/flock/bus/doors.py:111-140`). This agrees with h-vab `FLOW` §3 and `NAMING` invariant 5. The caveat is malformed data: a raw queue writer can bypass the sender boundary, so some byte-decidable defects are necessarily discovered after custody. |
| Switch reads all 256 header bytes and mutates TTL/hops | **Confirmed.** Parsing is constant-size rather than whole-body, but it validates source, destination, TTL and hops (`src/flock/bus/envelope.py:217-239`), then splices both counters (`src/flock/switch/service.py:143-151`, `src/flock/bus/envelope.py:251-265`). h-vab `FLOW` §4 and `NAMING` §§3, 7-8 freeze the switch at source and destination and give hop accounting to a router. |

## 8. Answer 1 — behaviour already shared

The two designs agree on more of the forwarding contract than their different
wire shapes suggest:

- **Arrival establishes attribution.** h-flock derives the sender from the
  popped egress key and overwrites a contrary claim
  (`src/flock/switch/service.py:115-141`). h-vab `FLOW` §2 steps 5-7 and
  `NAMING` §5 derive source from the bound arrival port. They disagree on how a
  forged claim reaches that point, not on the source of truth.
- **The payload is outside local forwarding.** h-flock decodes only its fixed
  header (`src/flock/bus/envelope.py:189-239`) and preserves the body during
  source and counter splices (`src/flock/bus/envelope.py:242-265`). h-vab
  `FLOW` §§1, 4 and `NAMING` §§1, 3 keep payload and non-forwarding headers away
  from the switch.
- **Unknown local unicast is not flooded.** h-flock requires roster membership
  and dead-letters a miss (`src/flock/switch/service.py:174-177`). h-vab
  `FLOW` §2 step 8 and `NAMING` §§4, 7 make an in-domain miss unroutable.
- **Broadcast excludes its source and is local.** h-flock computes recipients
  as the roster minus sender (`src/flock/switch/service.py:153-172`). h-vab
  `FLOW` §2 step 8 and `NAMING` §6 specify the same source exclusion and domain
  boundary. Empty fan-out is successful in both designs.
- **Forwarding never waits for a failed target.** h-flock bounds ingress,
  rolls an over-bound copy to the sender's dead queue, and does not kick that
  target (`src/flock/switch/service.py:57-73`,
  `src/flock/switch/service.py:178-187`). h-vab `FLOW` §§2-3 and `NAMING`
  invariants 7 and 9 require bounded target queues and non-blocking failed
  delivery. The units and the point of admission differ, as §9 records.
- **Refusal is closest to the live caller.** Local address resolution and tag
  policy precede frame assembly and enqueue (`src/flock/bus/doors.py:55-84`),
  while failures discovered after a pop become dead letters. That is the
  operational form of h-vab's `FLOW` §3 decidability rule.
- **There is authoritative attachment state, not learning or flooding.** The
  roster is the current forwarding authority (`src/flock/bus/roster.py:6-18`).
  h-vab `NAMING` §§4, 7 uses explicit bind/unbind and an authoritative table.
- **Transport failure is observable and bounded rather than recursively
  addressed.** h-flock has per-sender dead queues (`src/flock/bus/resources.py:32-38`)
  and records a reason on switch failures; h-vab `FLOW` §3 and `NAMING` §9 use
  failed-delivery records with bounded retention and no addressable dead sink.

## 9. Answer 2 — divergences and their status

| Divergence | Status | Assessment |
|---|---|---|
| **Observers share the forwarding loop.** | Accidental architectural debt. | `Switch.run()` schedules maintenance before each forward and one failure boundary covers all five (`src/flock/switch/service.py:199-220`). h-vab `FLOW` §8 is cleaner: observation cannot delay forwarding if it is outside the loop. This says nothing about whether h-vab's unbuilt observer API is sufficient. |
| **Policy is sender-side, not part of selection.** | Deliberate. | `require_allowed()` runs before `build()` (`src/flock/bus/doors.py:55-70`), while the switch has only membership (`src/flock/switch/service.py:174-177`). Build 54 chose immediate sender feedback and fresh Redis policy. h-vab `NAMING` §4 proposes destination admission in the forwarding table but explicitly leaves its shape open. The table mapping in §3 of this build was therefore false. |
| **Source forgery is corrected and recorded, not rejected.** | Deliberate. | The queue name is authoritative and a mismatch is stamped (`src/flock/switch/service.py:115-141`). Rejecting there would allow a raw writer to destroy another participant's traffic. h-vab `FLOW` §2 step 1 and `NAMING` §5 instead make fabric fields unencodable at the client type and reject them at the adapter. That stronger structure does not exist behind h-flock's `send(source=...)` API. |
| **Delivery depends on one doorbell per frame.** | Accidental, measured liveness gap. | There is one spawn after each accepted forward and no later discovery in this fabric (`src/flock/switch/service.py:75-99`, `src/flock/switch/service.py:164-187`). Build 73 left a terminal frame in ingress. h-vab `FLOW` §2 step 11 and `NAMING` invariant 6 make queue state level-triggered. |
| **TTL and hops are local-switch fields.** | Deliberate Build 73 decision, but the tighter h-vab read-set is the better layer boundary. | h-flock reads and advances both on every local forward (`src/flock/bus/envelope.py:217-239`, `src/flock/switch/service.py:143-151`). A local L2 switch cannot create an inter-domain loop, so h-vab `FLOW` §§4, 6 and `NAMING` §§3, 8 place hop accounting in the router that can. That removes two mutable fields and a failure branch from L2. It cannot simply be removed today: h-flock has no router, and its verified v4 contract presently bounds repeated forwarding of the same frame. Moving it is a future wire and router decision, not a documentation correction. |
| **Queue bound is count-based and checked after `RPUSH`.** | Deliberate implementation, different contract. | h-flock accepts the write, uses returned depth, then removes the newest copy and dead-letters it if depth exceeds 300 (`src/flock/switch/service.py:57-73`, `src/flock/switch/service.py:178-185`). h-vab `FLOW` §§2-3 and `NAMING` §9 specify byte bounds, `packet_too_large`, and synchronous `port_congested` before custody. h-flock's bound was measured to stop useless kicks; h-vab's stronger admission semantics are unmeasured. |
| **Broadcast is a Redis fan-out pipeline followed by per-target rollback.** | Deliberate current mechanism; h-vab specifies a different atomic shape. | h-flock pushes every copy in one pipeline, then individually rolls back over-bound targets (`src/flock/switch/service.py:153-172`). h-vab `FLOW` §2 steps 8-10 stages the full fan-out transaction and commits once. Neither design's prose alone proves behaviour under a mid-command Redis failure. |
| **Addressing is `pod:tenant:agent`, with bare `all`.** | Deliberate product model. | Frame resolution accepts only the local pod and tenant (`src/flock/bus/envelope.py:37-71`); broadcast is the special destination `all`. h-vab `FLOW` §§2, 6 and `NAMING` §6 has `domain/station`, qualified `domain/all-stations`, and a router for foreign domains. h-flock's outer pod namespace has no h-vab analogue. |
| **The switch mutates source as well as counters.** | Deliberate, but it means h-flock is not h-vab's mutation-free switch. | Fixed-offset source stamping preserves body bytes (`src/flock/bus/envelope.py:242-248`). h-vab `NAMING` invariants 2-3 permit reading only two fields and no mutation; its fabric stamping occurs before its switch decision. |
| **Custody is JSON-line evidence with crash gaps.** | Deliberate bounded observability. | `popped` is emitted after destructive `BLPOP` and before validation (`src/flock/switch/service.py:111-125`), and receive emits only after its own pop and parse (`src/flock/bus/doors.py:103-123`). h-vab `FLOW` §3 specifies failed-delivery state and durable loss counters but does not specify a joinable custody ledger or atomic queue-and-record transition. |

## 10. Answer 3 — problems h-vab's design addresses that h-flock has not

These are design coverage advantages, not proven fixes:

1. **The terminal strand.** A level-triggered arbiter plus drain-to-empty gates
   in h-vab `FLOW` §2 steps 4 and 11 removes correctness dependence on a single
   notification. h-flock has only the post-forward spawn
   (`src/flock/switch/service.py:164-187`). Build 73 measured the resulting
   terminal strand. h-vab has not implemented or fault-tested its arbiter, gate,
   or attach/detach races.
2. **Structural attachment authority.** h-vab `FLOW` §§1-2 and `NAMING` §5
   separates a client header from fabric-stamped fields and binds a non-optional
   address to a port. h-flock's public send still accepts caller-provided
   `source` (`src/flock/bus/doors.py:43-54`) and only later corrects it in the
   switch. The design removes an invalid state that h-flock currently detects.
3. **Observer isolation.** h-vab `FLOW` §8 makes observation unable to stall the
   forwarding loop by construction. h-flock executes five maintenance calls on
   that loop (`src/flock/switch/service.py:199-220`).
4. **A complete local/foreign forwarding rule.** h-vab `FLOW` §§2, 6 and
   `NAMING` §4 gives foreign misses to a router station while local misses fail.
   h-flock rejects every non-local destination during resolution
   (`src/flock/bus/envelope.py:53-64`) and has no fabric-level route.
5. **Byte-accounted admission and oversize distinction.** h-vab `FLOW` §§2-3
   distinguishes `packet_too_large` from retryable `port_congested` and bounds
   both sides by bytes. h-flock validates body shape but has no size limit
   (`src/flock/bus/envelope.py:100-175`) and bounds destination depth by count.
6. **Detach-race and loss-accounting vocabulary.** h-vab `FLOW` §3 distinguishes
   `target_detached`, requires a failed-delivery record per fan-out target, and
   calls for durable monotonic loss counters. h-flock detects only current roster
   absence (`src/flock/switch/service.py:174-177`) and has logs plus bounded dead
   queues, not durable counters in the scoped fabric.
7. **Single-writer and pre-custody types.** h-vab `FLOW` §7 and `NAMING`
   invariants 1 and 8 propose handle types that make queue ownership and the
   pre-/post-custody boundary structural. h-flock exposes key construction and
   accepts direct Redis writes; its guarantees are runtime checks
   (`src/flock/bus/keys.py:51-63`).

## 11. Answer 4 — h-flock requirements absent from h-vab

### 11.1 Recheck of Build 46's eight conflicts

| Build 46 conflict | After Builds 47-75 |
|---|---|
| 1. `packet_too_large` / `port_congested` would change synchronous edge behaviour. | **Still holds.** h-flock has no payload-size refusal and destination saturation is discovered after the switch push (`src/flock/switch/service.py:178-185`). h-vab `FLOW` §§2-3 deliberately moves both decisions to the live sender. |
| 2. h-flock returns an ID minted before fabric custody, while h-vab stamps it inside. | **Still holds.** `build()` creates `stream_id`, then `send()` enqueues and returns it (`src/flock/bus/envelope.py:119-130`, `src/flock/bus/doors.py:68-89`). h-vab `FLOW` §2 step 6 and `NAMING` §5 give ID stamping to the fabric after pop. |
| 3. `send(source=...)` cannot structurally attest a bound source. | **Still holds.** Source remains a public argument (`src/flock/bus/doors.py:43-54`). h-vab's bound `Port`/adapter handle has no current h-flock equivalent. |
| 4. h-vab rejects a forged fabric source; h-flock corrects it. | **Still holds and is explicitly deliberate.** The correction and `source_stamped` record remain (`src/flock/switch/service.py:129-142`). |
| 5. Field and lineage semantics differ. | **Still holds, with newer names.** h-flock v4 uses `kind`, independent `stream_id` and `correlation_id`, and `ts` (`src/flock/bus/envelope.py:119-130`). h-vab `NAMING` §5 uses `type`, fabric `id`, `flow`, and `arrived`, with absent flow defaulting to ID. This is semantic, not just a rename. |
| 6. Program boundaries do not match. | **Still holds.** h-flock's switch both forwards and schedules five maintenance services (`src/flock/switch/service.py:190-220`); send/receive are library doors (`src/flock/bus/doors.py:43-143`). h-vab `FLOW` §§1, 7 defines three programs and an external observer. |
| 7. Addressing does not match. | **Still holds.** h-flock has `pod:tenant:agent` and local-only resolution (`src/flock/bus/envelope.py:37-71`); h-vab `NAMING` §6 has `domain/station`, no outer pod, and router-mediated foreign domains. |
| 8. A rolling dual-wire compatibility window conflicts with a pure replacement. | **No longer holds as an active requirement.** Builds 63 and 73 chose hard wire breaks. Transport queues and delivering locks are explicitly purged at boot while durable boards remain (`src/flock/bus/resources.py:32-40`, `src/flock/bus/resources.py:49-78`). A future break still needs the same explicit decision, but h-flock no longer promises an in-flight dual-read window. |

### 11.2 Additional implemented requirements h-vab does not cover

- **Joinable custody across success and failure.** h-flock carries stream and
  correlation IDs in its fixed header (`src/flock/bus/envelope.py:9-17`,
  `src/flock/bus/envelope.py:201-239`) and records sent, popped, forwarded,
  kick, receive, open and dead outcomes. h-vab mentions observation and failed
  delivery but specifies neither a complete custody record set nor join rules.
- **Malformed post-custody bytes.** h-flock records a best-effort pop before
  validation and preserves a valid header's identity even when its body is
  corrupt (`src/flock/switch/service.py:41-55`,
  `src/flock/bus/doors.py:111-121`). h-vab's `FailedDelivery.record(packet, ...)`
  assumes a packet exists; it does not say how bytes that cannot become a packet
  remain attributable.
- **Byte-identical opaque bodies under correction and hop accounting.** h-flock
  uses fixed-offset splices (`src/flock/bus/envelope.py:242-265`), a property
  verified in Builds 72-73. h-vab says the switch mutates nothing, but does not
  specify or measure codec preservation at its stamping adapter/fabric seam.
- **The product's trust and namespace constraints.** h-flock's key grammar
  reserves product names and rejects all-digit agents because of measured tmux
  ambiguity (`src/flock/bus/keys.py:5-31`). h-vab `NAMING` §6 allows an
  all-digit station and has no pane-delivery boundary, so its grammar cannot
  prevent that product failure.
- **One-shot delivery and process custody.** Successful forwarding starts a
  distinct port process and records only that start (`src/flock/switch/service.py:75-99`).
  h-vab has gates and doorbells but does not specify supervision, process
  lifetime, spawn failure, zombie handling, or how a receiving station proves
  consumption.
- **Current policy semantics.** Absent or empty policy permits; otherwise source
  export and destination import must intersect (`src/flock/bus/policy.py:14-41`).
  h-vab `NAMING` §4 leaves its permission-table representation open and does not
  express tag communities or their absent-policy behaviour.

## 12. Answer 5 — the 67 comment lines

The scope contains exactly 67 lines whose first token is `#`, grouped into 14
comment blocks. They are not all measurements. The useful review unit is the
block: splitting a measured rationale across physical lines would inflate its
importance.

| Comment block | h-vab coverage | Must survive a rebuild? |
|---|---|---|
| A successful `Popen` proves an attempt, not a pop (`src/flock/switch/service.py:90-91`). | h-vab `FLOW` §2 makes a doorbell non-authoritative but defines no custody event semantics. | **Yes**, wherever the notification/process seam lands. A kick must not be reported as delivery. |
| L3 is opaque to local forwarding (`src/flock/switch/service.py:127-128`). | Direct agreement with h-vab `FLOW` §4. | **Yes**, already supplied by the design. |
| Arrival queue, not claimed source, is authoritative; correct rather than let a raw writer destroy traffic (`src/flock/switch/service.py:131-133`). | h-vab `FLOW` §2 and `NAMING` §5 prevent the client encoding fabric source and reject it earlier. They do not model a bypassing raw queue writer. | **Yes if h-flock's direct Redis capability remains.** A typed adapter would replace, not merely delete, this rationale. |
| Ignore `SIGCHLD` after 65 persistent zombies in 100 deliveries (`src/flock/switch/service.py:224-232`). | h-vab does not specify notification process lifetime or child reaping. | **Yes if notifications still spawn one-shot processes.** It is measured operating-system behaviour absent from the design. |
| Poll interval is configurable because offices trade feed latency against filesystem polling (`src/flock/switch/service.py:243-245`). | h-vab's observer is abstract and has no scheduling model. | **Yes if polling remains**, though this is rationale rather than a measurement. |
| Spaces mean an unallocated counter in a frozen-width older header (`src/flock/bus/envelope.py:91-92`). | h-vab specifies unknown versions rejecting but no reserved-width evolution rule. | **Yes for v4 compatibility.** Rebuilding packet types does not erase already verified wire evolution semantics. |
| Corrupt body with valid header stays joinable; malformed header does not (`src/flock/bus/doors.py:115-116`). | h-vab's failed-delivery primitive assumes a valid `Packet` and does not cover failed packet construction after custody. | **Yes.** This is a real observability boundary the design leaves undefined. |
| Do not print custody telemetry into an agent pane (`src/flock/bus/logging.py:65-79`). | h-vab has no panes, agent terminals, or product information boundary. | **Yes.** This block is duplicated in the source, but the measured constraint itself must survive. |
| One complete stdout write plus explicit flush prevents interleaved or indefinitely buffered JSON records (`src/flock/bus/logging.py:82-89`). | h-vab defines alert concepts, not a multi-process record transport. | **Yes.** Without it, the evidence used to establish custody can become unparsable or late. |
| Observation failure never fails a command (`src/flock/bus/logging.py:98-99`). | h-vab structurally places observation off-path, which would make this less necessary, but it does not specify local logging failure. | **Yes while logging remains in command processes.** |
| RESP `SET`/`HSET` belong to the measured one-shot control path (`src/flock/bus/resp.py:113-115`). | Outside h-vab's packet fabric and absent from its design. | **Yes in this library**, although it should not drive a fabric rebuild. |
| `all` cannot also be an agent (`src/flock/bus/keys.py:6-7`). | h-vab solves the analogous collision with `all-stations` reservation in `NAMING` §6, but not h-flock's existing wire token. | **Yes until the wire token changes.** |
| All-digit agents silently target the wrong tmux window; measured with windows `1`, `2`, and named `2` (`src/flock/bus/keys.py:10-20`). | h-vab `NAMING` §6 expressly permits all-digit station labels and has no tmux edge. | **Yes.** This is the clearest measured product constraint h-vab does not prevent. |
| Dotted resource keys must validate each segment without bypassing name restrictions (`src/flock/bus/keys.py:35-39`). | h-vab hides queue names behind handles but specifies no Redis resource grammar. | **Yes while Redis keys remain externally composed.** |

The blocks that most clearly encode measured facts h-vab does **not** prevent
are child reaping, terminal telemetry isolation, atomic and timely JSON-line
records, malformed-body custody joinability, and the all-digit tmux collision.
The direct-Redis source-correction rule also survives unless h-flock actually
acquires h-vab's structural port handle. The other blocks are shared principles,
current-wire compatibility, or implementation rationale rather than evidence
for a gap in h-vab.

## 13. Boundary of the comparison

h-vab's level-triggered drain, typed attachment, byte bounds and external
observer are plausible answers to real h-flock gaps. They remain unverified
designs. Conversely, h-flock's one-shot concurrency, fixed-width v4 splicing,
custody logs, count bound and source correction are implemented and measured,
but implementation does not make their trade-offs universally preferable.
This review intentionally stops at that boundary.
