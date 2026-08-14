# Build 67 — fault stress results

Tested commit `251b13d` on the disposable `stress67` tenant. This tests the
switch and port under faults; it does not implement or claim watchdog recovery.

## Results and negative controls

| fault | clean control | injected observation |
|---|---|---|
| A — enrolled destination cannot consume | 25 frames to an API destination drained; ingress and egress both reached zero | A paused, enrolled API destination retained all 500 frames after egress drained. Redis grew 183,280 bytes, or 366.56 bytes per retained frame. Forwarding took 50.58 seconds (9.89/s). Container CPU had 22 samples: median 1084.93%, range 108.77–1366.48%. |
| B — stale `delivering` owner | 10 frames drained and zero `flock.port stress-clean` processes remained | A real `run_port` holder was killed after its `HSETNX`. The tag remained, ingress retained all 25 later frames, and 25 later kicks left 25 waiting port processes. |
| C — non-tmux participants | Kicked API and control frames both cleared their ingress queues | One un-kicked frame remained in API ingress and one in control ingress. `Watchdog._agents()` returned only `architect` and `sme-2`; it omitted both stranded participants. |
| D — `BLPOP` to first-record gap | Three same-source frames produced three `opened` records: no loss, duplicate, strand, or parse failure | The controlled switch was killed after `BLPOP` and before `popped`. Reconciliation found two delivered-once and one attributed loss, with zero duplicates, unexplained losses, strands, or parse failures. Same-source FIFO records bracket the loss between predecessor pop `1786739503.478` and successor pop `1786739508.398`. |

Every clean control was run before its paired injection. Thus each detector was
shown both clean and red; a detector that always finds its fault would have
failed its clean control.

## Case A ceiling

There is no configured Redis hard limit, so the ceiling needs an explicit
operational threshold. At **1 GiB of Redis growth**, the measured slope projects
to **2,929,238 retained frames**. At the measured 9.886 forwards per second,
that threshold is reached in **296,298 seconds (82.3 hours)** of steady traffic.
This is a linear extrapolation from 500 frames, not a claim that Redis fails at
1 GiB. Host/container memory was already roughly 603–692 MiB during the run and
is not represented by the per-frame Redis slope.

## What a watchdog must observe

- **A:** Per-participant ingress depth and growth rate, correlated with
  successful kicks and the absence of pop/open progress. Depth alone cannot
  distinguish a slow consumer from a dead one.
- **B:** Delivering-owner identity or lease age, ingress depth, and kicks that
  lose ownership. Re-kicking from depth alone only adds waiting processes.
- **C:** Roster-wide ingress depth for every `port_type`, rather than the
  tmux-only set returned by `Watchdog._agents()`.
- **D:** A durable custody sequence for each source FIFO — sent, preceding pop,
  following pop — plus switch process generation. The lost frame has no
  frame-local custody record for a watchdog to read.

These observations characterize signals; they do not resolve the blocked
slow-versus-dead policy decision in `DESIGN-layers` section 8.

## Safety and evidence

Across the D control and injection, zero duplicates held. The injected loss was
FIFO-attributed and no loss remained unexplained. All Docker-log, dead-queue,
ingress, and event-timestamp parse-failure counts were zero.

The checksummed lab-local evidence is in
`/home/h-lab/tmux-build67/evidence`, with its manifest at
`/home/h-lab/tmux-build67/evidence.sha256`. The scoped tenant was removed with
`docker compose down -v`; only the operator-owned `h-cli` container remained.

Local verification: `375 passed, 5 subtests passed`.
