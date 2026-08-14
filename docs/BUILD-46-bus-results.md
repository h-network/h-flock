# Build 46 — h-vab adaptation trial results

Worked from `origin/vabtrial` at
`51dcc5ac94da5138d9449eb860ef54aedf340472`. The implementation commit before
this report is `9b8de57` on `bus/build-46-vabtrial`. Nothing targets main.

## Verdict

**No.** The design fits the forwarding seam and preserves locatable custody,
but it cannot preserve the edge's behavior and also implement h-vab's custody
contract. A caller that previously appended without a capacity outcome can now
receive synchronous `packet_too_large` or `port_congested`. An agent can tell
that difference. Hiding either result would make the adaptation cease to be the
h-vab design being tested.

This is a successful negative trial, not a migration recommendation.

## What moved in the trial

- `flock.fabric` adds bound `Port` handles and the `attach` / `send` / `receive`
  API.
- The client grammar carries `version`, `destination`, `type`, `flow` and
  payload. It has no source, id, arrived, or hops slot; attempts to submit those
  fabric fields are rejected.
- After the ingress custody append, fabric code stamps `source`, `id`,
  `arrived`, and `hops`. The forwarded packet has exactly the specified eight
  header fields plus its payload.
- `ForwardingTable` and `Switch` implement exact one-domain station lookup and
  `all-stations` fan-out. `Switch.select` passes only packet source and
  destination to the table.
- Ingress and egress have byte caps. Oversize is rejected before custody;
  ingress congestion fails synchronously; full target egress dead-letters only
  that target and does not block the forwarding loop.
- The existing bus send/receive functions are compatibility edges. Openers
  still receive the v1-shaped object they already consume, so tmux paste,
  boards, API mailboxes, control, presence, and office behavior above the seam
  did not need implementation changes.

## Where the models disagree

1. **Synchronous capacity failure changes the edge.** h-vab defines
   `port_congested` as a real send failure and `packet_too_large` before
   custody. h-flock's office send previously offered neither outcome. This is
   the decisive failure under Build 46 §5.
2. **A returned stream identity precedes h-vab's stamping point.** h-flock send
   returns `stream_id` and logs `sent` synchronously. h-vab mints `id` after
   successful ingress append, when the arbiter knows the arrival port. The
   trial uses a fabric-owned receipt beside, not inside, the client grammar so
   the later stamp can preserve the returned id. That sidecar is additional
   seam state absent from the settled h-vab flow.
3. **The old send signature cannot structurally attest source.** A bound `Port`
   makes source absent from the client grammar, as h-vab requires. The legacy
   `send(... producer=...)` compatibility wrapper binds a port from the same
   caller-provided name, so it does not strengthen callers that retain access
   to that signature. True attestation requires migrating callers to handles,
   which changes their interface.
4. **Correction becomes rejection.** A raw v1 envelope written to an ingress
   port is now malformed client input and dead-letters. It is not corrected and
   no `producer_stamped` event exists. This makes forgery non-routine, as h-vab
   intends, but removes Build 36's correction behavior.
5. **The eight fields carry h-flock semantics, but not perfectly.** Envelope
   `kind` maps directly to packet `type`; `correlation_id` maps to `flow`; and
   packet `id` maps to `stream_id` at the receive edge. The semantic mismatch is
   that h-vab defaults flow to id, whereas h-flock independently mints a
   correlation id for each initial send.
6. **The three programs do not match current process boundaries.** h-flock's
   port name covers both the sending CLI edge and the receiving one-shot
   delivery edge. Its process named switch performs local switching plus five
   maintenance jobs. The trial isolates the two-header `Switch` decision in
   code, but a faithful three-program deployment would require a process split
   beyond this one-domain trial.
7. **Addressing has one unmatched level.** Tenant maps cleanly to h-vab domain
   and agent/participant maps to station. Pod remains an outer Redis/deployment
   namespace with no packet-address analogue.
8. **In-flight upgrade compatibility is not pure h-vab.** Receive accepts old
   v1 entries already in ingress so an upgrade does not destroy custodied work.
   New sends never create that form. A pure packet-only receiver would reject
   them, making rollout behavior visible at the edge.

## Pass/fail criteria

### Product

Real tenant installed by `setup.sh` on h-lab, assigned tenant `bus-lab`, ports
8100/8101. Raw acceptance output:

```text
══ install — driving setup.sh as a person would ══
wrote container/.env
Tenant 'bus-lab' is healthy.
  default   claude  NEEDS LOGIN
  default   codex   NEEDS LOGIN
  default   agy     NEEDS LOGIN

══ health ══
  container: healthy
architect sme-2

══ plumbing check and failure simulator ══
== 1. doors ==
== 2. agent -> agent message ==
== 3. board ==
== 4. app client ==
== 5. app -> agent, as itself ==
== 6. agent -> app, the return path ==
== 7. cursor resume ==
== 8. isolation between clients ==
== 9. lifecycle ==
== 10. dead-letter ==
== 11. booted and hired agents get the same environment ==
== 12. failure simulator ==
=== sim-blocked: failure simulator ===
== Case 1: wedged_process (CLI replaced by a non-consuming process) ==
== Case 2: trust seeding prevents the picker ==
== Case 3: login_prompt_known_gap (unauthenticated codex profile) ==
== Case 4: login_prompt_claude (unauthenticated claude profile) ==
sim-blocked: PASS=19 FAIL=0
=== sim-blocked teardown: restoring tenant state ===
PASS=25 FAIL=0

══ result ══
  passed: install, health, plumbing, simulator, console reachable
```

Unit evidence:

```text
344 passed, 5 subtests passed in 14.05s
```

### Custody

Yes, the trial can still answer where a packet stopped without a new bespoke
observer. It retains h-flock's existing five record types at the compatibility
edge and keys them with packet id. The successful ingress append is custody;
`popped` locates removal from it, `forwarded` locates target append,
`received` locates edge custody, and `opened` locates application dispatch. A
missing successor still identifies the boundary. The existing window-log
tailer remains the observer; no second observation system was added.

Raw short multi-agent Nemotron trace, using only
`http://172.16.0.11:8000`, includes this complete exchange:

```text
{"module":"port","event":"sent","stream_id":"21ec57b6e7534e118bf74d0411a0e1c8","producer":"architect","recipient":"sme-2"}
{"module":"switch","event":"popped","stream_id":"21ec57b6e7534e118bf74d0411a0e1c8","producer":"architect","recipient":"sme-2"}
{"module":"switch","event":"forwarded","stream_id":"21ec57b6e7534e118bf74d0411a0e1c8","producer":"architect","recipient":"sme-2"}
{"module":"port","event":"received","stream_id":"21ec57b6e7534e118bf74d0411a0e1c8","producer":"architect","recipient":"sme-2"}
{"module":"port","event":"opened","stream_id":"21ec57b6e7534e118bf74d0411a0e1c8","producer":"architect","recipient":"sme-2"}
{"module":"port","event":"sent","stream_id":"d543f5886aef4983b4bbf189cc6aa87a","producer":"sme-2","recipient":"architect"}
{"module":"switch","event":"popped","stream_id":"d543f5886aef4983b4bbf189cc6aa87a","producer":"sme-2","recipient":"architect"}
{"module":"switch","event":"forwarded","stream_id":"d543f5886aef4983b4bbf189cc6aa87a","producer":"sme-2","recipient":"architect"}
{"module":"port","event":"received","stream_id":"d543f5886aef4983b4bbf189cc6aa87a","producer":"sme-2","recipient":"architect"}
{"module":"port","event":"opened","stream_id":"d543f5886aef4983b4bbf189cc6aa87a","producer":"sme-2","recipient":"architect"}
```

The 60-second local-model run produced six inter-agent/API packets visible in
the captured trace, all six with complete five-record sets and zero dead
letters: **6 sent, 6 popped, 6 forwarded, 6 received, 6 opened, 0
dead-lettered**.

### Hot path

The `Switch` itself grew no branch beyond group-versus-exact selection. Its
decision reads `source`, `destination`, and `ForwardingTable`; a test poisons
`type` and payload with unreadable objects and the decision still succeeds.
Stamping happens before it. Byte-capacity and per-target dead-letter decisions
happen after selection, outside `Switch`.

## Recommendation

Do not migrate h-flock to this fabric under a promise that its edge behavior is
unchanged. If the operator wants h-vab custody semantics enough to version the
send edge, the forwarding core, addressing, packet type/flow mapping, and
existing observation records are a credible fit. Without that explicit edge
version, stop at this trial branch.
