# Build 113 — does a burst survive, and does the delay decide it?

**Lane: `acceptance`. Base: `main` at `b95ef40`.** Lab.

## The structural half is settled — do not re-derive it

`src/flock/port/deliver.py:181-197`: the port acquires a per-agent `delivering`
tag with `hsetnx`, spins until it wins, calls `deliver_one(...)`, and releases in
a `finally`.

⚠ **`deliver_one` returns when `send-keys` returns.** So the lock is held across
our *write* into the pane and released before the CLI has *read* it.

**Two deliveries can be perfectly serialised by the lock and still reach the CLI
faster than it processes them.** ⚠ **The only thing spacing consecutive
deliveries is `ENTER_DELAY`** — 0.5 s at the default, **zero at zero.**

## Why build 112 could not see this

Build 112 sent **sequentially, one `office send` completing before the next was
issued.** ⚠ **A full client round trip between envelopes supplies the spacing the
delay exists to guarantee**, so 50/50 at both settings is true and narrower than
it reads. It measured a single paste+Enter, not consecutive ones.

## The method — use the fabric's own burst, not racing clients

⚠ **Do NOT race `office send` processes.** That was the calibration method and it
confounds client concurrency with delivery spacing.

**Use `pause` → queue → `resume`:**

1. **Pause** the target agent.
2. **Send N envelopes** with unique markers — they queue in `ingress`, undelivered.
3. **Resume.** ⚠ **`resume_agent` kicks once per queued ingress envelope**, so the
   port drains them **back to back with no client round trip between them.**

**That is the real scenario**: an agent busy or paused, mail accumulating, then a
burst on resume. It is also what happens in a multi-agent session when several
agents write to one agent while it is working.

Run it at **both** delay settings. Count as in build 112 — **markers actually
submitted, from the CLI's own session transcript**, not a pane scrape. Your Ink
five-turn finding applies here more, not less: a burst is exactly when a scrape
under-reports.

## ⚠ State the prediction before you run it

**My prediction, written down so the run can contradict it:** `delay=0` loses or
coalesces markers; `delay=0.5` does not, or loses fewer.

⚠ **If the run contradicts that, the run is right and the prediction was wrong.**
Say so plainly. **A confirmed prediction and a refuted one are both results** —
and the refuted one is worth more, because the inference is currently mine and
unverified.

⚠ **Report `opened` counts alongside.** If markers are lost while `opened` reads
N-of-N, that is the `opened`-proves-delivery contradiction — already filed —
observed live rather than argued.

## Out of scope

⚠ **Do not change `ENTER_DELAY`** whatever the result. A number that justifies
keeping it is not a licence to tune it, and a number that questions it is one run.

## Report

Per `BUILD-83`. Name the CLI and version. Hash and push the evidence.
