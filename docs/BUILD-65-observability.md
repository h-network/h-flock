# Build 65 — is every handover, every failure, every forward actually logged?

> ⚠ **The figures below name no host, and the spread between our two is 130×**
> — identical scripts read **6.5/s on the 4-vCPU lab** and **853/s on h-oracle**.
> Read every `/s` here as this build's own evidence on an unrecorded host,
> **never as a capability**. `BUILD-CONVENTION` §3.0 is the rule that followed;
> [`DRIFT`](DRIFT.md) §4 is the finding.

> **Base on `main`.** Branch `bus/build-65-observability`, push to origin.
> Owner: `bus` (`flock/bus/logging.py`, `flock/switch`, `flock/port`).
> ⚠ **Audit first. The fix is the second half and may be smaller than it looks.**

## 1. The question

An envelope moves through handovers: a port accepts it, writes egress, the
switch pops it, forwards it, kicks a port, that port pops it, an opener takes
it. **Can every one of those be reconstructed from the log alone?**

We already know of one that cannot.

## 2. The known hole, established by build 58

`seq 9956` (`cons-57`) and `seq 9990` (`cons-91`) sat intact in ingress **forever**. In the log it looks like
this:

```
forwarded  stream_id=21aaaee…
(nothing)
```

⚠ **`forwarded` with no successor is indistinguishable from three different
states**: still in flight, stranded forever, or the log being read too early.
`tmux` could only identify it by inspecting queue depth — **outside the log**.

⚠ **The verifier does not catch it.** `watchdog/verification.py` reads
`pending.verify`, which is written **at delivery time**. A stranded envelope
never reaches delivery, so it never gets a marker, so the verifier never judges
it. Confirmed by reading, not assumed.

## 3. Audit — the deliverable, as a table

Every transition, with the record that proves it. Cite `file:line` for each —
`tools/check_citations.py` now verifies those, so wrong ones will be caught.

Start from these and **find the ones I have missed**:

| transition | record? |
|---|---|
| port accepts a send | `sent` |
| refused by policy | `send_refused` |
| refused as non-local | ⚠ verify — same record, or none? |
| written to egress | ⚠ implied by `sent`, or separate? |
| switch pops | `popped` |
| source corrected | `source_stamped` |
| switch forwards to ingress | `forwarded` |
| **switch kicks a port** | ⚠ **only on failure** (`error`, "port kick failed"). A successful kick emits nothing |
| port pops from ingress | `received` |
| opener runs | `opened` |
| opener raises / unknown kind | `dead_lettered` |
| destination not in roster | `dead_lettered` |
| **kicked port dies before popping** | ⚠ **NOTHING** |
| broadcast fan-out | `forwarded` with `count` |

## 4. ⚠ The constraint that makes this interesting

**Some of these cannot be logged where they happen, because nothing there
knows.** The switch cannot log "the port died before popping" — it kicked and
moved on. Detecting a strand needs an **observer**: something that notices
ingress non-empty with no progress.

✅ **The observer already exists: it is the WATCHDOG** (`DESIGN-layers` §8).
`flock/watchdog` polls agents, judges blocked and absent and raises alerts, and
it runs outside the switch. **Classify such transitions as "watchdog's job" —
do not invent a new component and do not build it here.**

⚠ **Do not build a sweeper inside the switch.** A sweeper changes delivery behaviour — it is the
liveness fix, it is a design decision, and it is mine and the operator's to
make. **This build establishes what is invisible; it does not make it visible by
changing how delivery works.**

⚠ **Cheap wins are in scope**: a record at a transition where the code already
knows and simply does not emit — the successful kick is the obvious candidate.
Judge whether it is worth the log volume and say why either way.

## 5. Prove it against real evidence

`tmux` kept an evidence bundle with checksums at
`/home/h-lab/tmux-build58-rerun/evidence-attempt4`. **Use it.**

Answer concretely: from that `docker logs` capture alone, with no queue
inspection, could you identify `seq 9956` or `seq 9990` as stranded rather than
in flight? ⚠ **My first version of this spec cited `seq 9935`, which was
attempt 3's strand, not attempt 4's.** `bus` verified the checksums and found
the right records — `popped` and `forwarded` and nothing after, for both.
⚠ **If the answer is no, that is the build's headline** — a 10,000-envelope
conservation run whose most interesting finding was invisible to the log.

## 6. Done when

- the §3 table is complete and every row cited, with citations passing
  `tools/check_citations.py`
- each silent transition classified: **cheap to emit** / **needs an observer** /
  **deliberately silent**
- cheap ones emitted; ⚠ **negative control** per
  [`BUILD-CONVENTION`](BUILD-CONVENTION.md) §1 — provoke each new record and
  show it appear, and show its absence when the transition does not occur
- the build-58 replay question in §5 answered plainly
- `python3 -m pytest -q` green (369 at the time of writing)
- ⚠ **`fabric-bench` 100×20 unchanged**: 2,000/2,000, ≥ 6/s. New records cost log
  volume, and build 47 proved the log is a shared resource

## 7. Reporting

`jira done`, then message `architect` with the table, the classification counts,
the build-58 replay answer, and — for anything needing an observer — what it
would take, without building it.
