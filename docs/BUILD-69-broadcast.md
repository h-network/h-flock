# Build 69 — broadcast has never been proven to conserve, and cannot be

> **Base on `main`.** Branch `tmux/build-69-broadcast`, push to origin.
> Owner: `tmux` — the harness is yours. ⚠ Touches `flock/bus/doors.py`
> (`bus`'s), who are on build 68 elsewhere in the tree.

## 1. The gap

**Every conservation result we have is unicast-only.** Build 58 and build 67
both send `cons-N → cons-M`. Broadcast has never been run, and the reason is
structural rather than an oversight.

For `destination: "all"` (`switch/service.py:101-113`):

- the switch emits **one** `forwarded` with `count=N`
- all N deliveries carry **the same `stream_id`** — it is one raw frame pushed to
  N ingress queues
- every `received` and `opened` reports `destination: "all"`, because the port
  emits from the envelope

⚠ **So `opened` for that `stream_id` is legitimately N.** The reconciler flags
`opened > 1` as a duplicate, so a broadcast to 20 participants reports **19
duplicates** — and a *real* broadcast duplicate hides inside that number
undetectably.

⚠ **At-most-once is therefore UNVERIFIABLE for broadcast today.** Not
unproven — unverifiable, with the evidence we emit.

## 2. The fix: the receiving port knows who it is

`run_port(agent=...)` is delivering **for a specific participant**. The custody
record should say so.

**Emit the port's own agent as `destination`, not the envelope's
`l2.destination`.** For unicast these are identical, so nothing changes. For
broadcast, each record names its actual recipient.

⚠ **The frame is untouched.** `l2.destination` stays `"all"` on the wire —
that is the L2 header and the switch's business. This changes what the *record*
says, not what the *frame* says, and the two were conflated because they happened
to agree for unicast.

⚠ **Then the conservation key becomes `(stream_id, recipient)`**, and "delivered
exactly once" means exactly what it says for both cases.

## 3. Update `CONTRACTS` §3

State that a custody record's `destination` is **the participant the record is
about**, which for a broadcast is one of N and not the literal `"all"`. ⚠ Say
that N records sharing a `stream_id` is **correct for broadcast and a defect for
unicast** — that distinction is the whole point.

## 4. Prove it

Extend `conservation.sh` with a broadcast phase — ⚠ **do not replace the unicast
one**, we would lose a proven result.

- 100 participants, a bounded number of broadcasts, mixed with unicast traffic
- reconcile on `(stream_id, recipient)`: **every recipient exactly once per
  broadcast**
- ⚠ **negative controls** per [`BUILD-CONVENTION`](BUILD-CONVENTION.md) §1:
  deliver one broadcast frame **twice to the same recipient** and prove it is
  caught as a duplicate; and **drop one recipient** and prove it is caught as a
  loss. **A key that has never rejected anything is not known to work**
- ⚠ **the switch kicks N ports for one forward.** Report the CPU and the
  concurrent port count against the unicast baseline — build 67 measured 1084%
  on a single doomed destination, and fan-out is the multiplier

## 5. Done when

- records carry the actual recipient; unicast records byte-identical to before
- broadcast conservation proven, both negative controls demonstrated
- `CONTRACTS` §3 updated
- `python3 -m pytest -q` green (375 at the time of writing)
- `fabric-bench` unchanged: 2,000/2,000, **≥ 6.45/s**, exact figure quoted
- one tenant at a time, lab-local output, checksummed evidence

## 6. Reporting

`jira done`, then message `architect` with the broadcast conservation numbers,
both negative-control proofs, the fan-out CPU and port count, and whether
anything about unicast changed.
