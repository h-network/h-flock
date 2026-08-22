# Build 70 — measure from the log we already write

> ⚠ **The figures below name no host, and the spread between our two is 130×**
> — identical scripts read **6.5/s on the 4-vCPU lab** and **853/s on h-oracle**.
> Read every `/s` here as this build's own evidence on an unrecorded host,
> **never as a capability**. `BUILD-CONVENTION` §3.0 is the rule that followed;
> [`DRIFT`](DRIFT.md) §4 is the finding.

> **Base on `main`.** Branch `bus/build-70-measure`, push to origin.
> Owner: `bus` — you built the measurement discipline and found the rounding bug.
> ⚠ Touches `container/scenarios/`, which `tmux` owns. Told.

## 1. The instrument is loading the system it measures

`fabric-bench.sh` reports **one wall-clock division**: envelopes ÷ elapsed. To
know when to stop, it polls:

```sh
NOW=$(docker logs "$CONTAINER" 2>&1 | grep -c '"event":"opened"')
sleep 1
```

⚠ **Every second, it re-reads the entire container log and greps it.** At 2,000+
envelopes that is megabytes, ~200+ times per run, on the same CPU as delivery —
**and it gets heavier as the run gets busier.** The instrument competes with the
thing it measures, hardest at the worst moment.

⚠ **And 1-second polling granularity is baked into every figure**, on runs where
the whole measurement is ~350 s.

**Meanwhile every record already carries `ts`, `stream_id`, `module` and
`event`** — a fully timed path per envelope. We throw it away.

## 2. What to build

**Read the log once, at the end. Compute everything from records.**

- **steady-state throughput** — `opened` events within the **middle 80%** of the
  delivery window, divided by that window. ⚠ Excludes ramp-up and the drain
  tail, which is where the noise lives
- **per-stage medians**, joined on `stream_id`: `sent→popped`,
  `popped→forwarded`, `forwarded→received`, `received→opened`. ⚠ **This is the
  diagnostic half** — "6/s" never said *where* the time went; these do
- **end-to-end p50 / p95 / p99**, not a mean. `BUILD-CONVENTION` §3 already
  requires medians for exactly this reason
- keep total delivered and dead-letter counts as they are — those are correct

⚠ **Poll for completion cheaply**: `LLEN` on the queues, or a bounded log tail,
not a full `docker logs` scan. **State what you chose and its cost per poll.**

## 3. ⚠ The gate: prove it is steadier

**Run it N ≥ 5 times on unchanged `main`** and report the spread of each metric.

| | today | required |
|---|---|---|
| wall-clock throughput | **35%** (5.22 / 6.00 / 6.40 / 6.45 / 8.12) | — |
| steady-state throughput | — | ⚠ **report it; if it is not materially tighter, say so** |
| per-stage medians | — | report the spread |

⚠ **A steadier number is the deliverable. If the new metric is just as noisy,
that is the finding** — it would mean the variance is real host contention
rather than instrument artefact, which changes what we do next and is worth
knowing either way. **Do not tune until it looks good.**

## 4. ⚠ Do not break comparability

Keep printing the old wall-clock figure alongside the new ones for now. Every
number in `docs/BUILD-*.md` is in the old units, and dropping it would orphan
two days of results.

## 5. Done when

- metrics computed from records; no repeated full-log scans during the run
- **N ≥ 5 runs on unchanged `main`**, spread reported per metric
- ⚠ **negative control** per [`BUILD-CONVENTION`](BUILD-CONVENTION.md) §1: feed
  it a log with a known-missing stage and show the per-stage figure refuses
  rather than silently averaging what remains
- old wall-clock figure still printed
- `python3 -m pytest -q` green (380 at the time of writing)
- ⚠ one tenant at a time, lab-local output

## 6. Reporting

`jira done`, then message `architect` with the per-metric spreads across the N
runs, the per-stage medians for one run, what the completion poll costs now, and
whether the variance turned out to be instrument or host.
