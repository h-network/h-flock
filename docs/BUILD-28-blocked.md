# Build 28 — `blocked`, without reading a screen

> [`BUILD-27`](BUILD-27-watchdog.md) §7 defined `blocked` as *we delivered and it
> was not consumed*, and proposed finding it by scraping. Measured: a consumed
> message stays visible in the transcript, so a whole-screen match marks healthy
> agents blocked, and separating transcript from input box needs CLI-render
> knowledge.
>
> **The system already computes this.** It just discards it.
>
> **Base on `main`.** Branch `bus/build-28-blocked`, push to origin.

## 1. The verdict exists and is thrown away

The router judges every delivery against a later `input` event, emits
`delivery_unverified` to stdout, and deletes the marker. **Nothing retains the
answer**, so anything that wants it has to re-derive it — which is what pushed us
toward a screen.

```
  <prefix>:agent:<name>:blocked   HASH   { since, stream_id }
```

| the router's verdict | the key |
|---|---|
| **unverified** | `HSET` — set `since` and the `stream_id`, if not already set |
| **verified** | `DEL` — something was consumed, so it is not blocked |

⚠ **Set on the first unverified, not on every one.** `since` must be when it
started, not when it was last observed — an agent blocked for an hour should say
an hour.

⚠ **Clear on any verified delivery.** That is the definition: something was
consumed. Never clear it on a timer — a stale `blocked` holds work, which is
safe; a stale clear sends work into a hole, which is not.

⚠ **The router writes it, not the watchdog.** It is derived from data the router
already has, so it belongs where the verdict is reached, and there is one writer.

## 2. What this removes

⚠ **No `capture-pane` anywhere in the system** — not in the data path, not in
observation. Delete the scrape from build 27 rather than leaving it disabled.

No transcript-versus-input-box problem, no wrapping, no per-CLI knowledge, and
nothing to update when a CLI reskins.

## 3. What it still does not catch

⚠ **The modal swallow.** claude writes an `input` record even when a picker eats
the message, so verify passes it and `blocked` will not fire. Unchanged and still
open — do not imply otherwise in any wording.

⚠ **An agent blocked before anything is sent** reads `idle` until someone
delivers. Correct rather than a gap: the harm exists only when work is being
sent.

⚠ **agy has no activity feed**, so its deliveries are never marked and never
judged. An agy agent can therefore never be `blocked`. Say so.

## 4. The watchdog uses it, and says so plainly

`blocked` becomes a fourth alert kind, and appears in a stall alert when set.

```json
{"v":1,"ts":"…","kind":"blocked","agent":"sme-2",
 "since":"…","stream_id":"…","unconsumed_s":420}
```

⚠ Still no envelope to any agent (build 27 §5). `office status` already reports
it and needs no change.

## 5. The simulation matrix — run all of it

Every failure we have actually seen, on the lab tenant. **Report the observed
`blocked` state for each**, not whether the code looks right.

| # | how to produce it | expected |
|---|---|---|
| 1 | healthy agent, message delivered and answered | **not blocked** |
| 2 | agent on a profile with no credential — sits at a login prompt | **blocked** |
| 3 | agent whose directory was never trusted — sits at the trust picker | **blocked** |
| 4 | `SIGSTOP` the CLI process, then deliver | **blocked** |
| 5 | deliver, then `SIGCONT` — a later delivery consumed | **clears** |
| 6 | `/model` picker open, then deliver | **not blocked** — the known hole (§3) |
| 7 | bare shell window (no CLI) | **never marked** — no verify marker at all |
| 8 | agy agent | **never marked** (§3) |

⚠ **6 must be reported as a miss, not quietly omitted.** A matrix that only lists
passes is not evidence.

⚠ **1 is the one that decides the build.** The scrape version failed exactly
here — it marked a healthy agent blocked because its consumed message was still
on screen. If this version does that too, it is no better and we stop.

## 5b. Measured, 2026-08-09 — the matrix

| # | case | result |
|---|---|---|
| 1 | healthy, delivered and answered | **not blocked** ✅ the check the scrape failed |
| 2 | no credential, *"Not logged in"* on screen | **MISS** — not blocked |
| 3 | trust picker open | **blocked** ✅ |
| 4 | `SIGSTOP`ped CLI | **blocked** ✅ |
| 5 | `SIGCONT` then a consumed delivery | **cleared** ✅ |
| 6 | `/model` picker | expected miss; the attempt was invalid (the command queued rather than opening a picker) — **unproven, not passed** |
| 7 | bare shell | **never marked** ✅ no verify marker written |
| 8 | agy | **never marked** ✅ |

⚠ **Row 2 is the finding, and it widens the known hole.** A claude sitting at
*"Not logged in"* still records an `input` when text is pasted, so verify passes
the delivery and `blocked` never fires. That is the **same mechanism as the modal
swallow**, observed independently: the CLI records that input arrived, not that it
was acted on.

**So the hole is not "modals". It is: any state where the CLI records input it
does not act on.** Login prompts and modals are two instances; there may be more.

⚠ **What it does catch is still worth having**, because row 1 passes. A trust
picker and a wedged process are real, and the scrape version was disqualified by
marking a *healthy* agent blocked — a false positive that would have made the
lead withhold work from agents that were fine.

### What this tells us about the screen

A scraper would only be needed for the row-2 class — *input recorded, not acted
on* — and nothing else. Rows 3, 4, 7 and 8 are already answered without one. That
is a much smaller job than the general "detect a stuck agent" we were sizing
earlier, and it is the only part still open.

## 6. Done when

- every row of §5 is reported with its observed result
- `since` on a long block reads from the first unverified, not the latest
- a verified delivery clears it
- `grep -rn capture-pane src/` finds nothing outside the session door
- `office status` reports it unchanged

## 7. Reporting

`jira done`, then message `architect` with the matrix results. ⚠ Name any
non-default settings **beside** the output — an alert quoted without the
thresholds that produced it reads as a contradiction.
