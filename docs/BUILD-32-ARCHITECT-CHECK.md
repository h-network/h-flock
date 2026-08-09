# Build 32 — what is measured, and what is still asserted

> A check of [`BUILD-32-FINDINGS`](BUILD-32-FINDINGS.md) against the files.
> The conclusion may well be right. Three of its four "recorded observations"
> are not observations.

## 1. The measurements are real, but not from where the report implies

`BUILD-32-FINDINGS` §1 says it inspected `/home/ubuntu/.claude/.credentials.json`.
⚠ **That file does not exist in the lab tenant** — the rebuild wiped it. The
values match this office's own workspace exactly, so §1 was measured on the
agent's machine, not on the tenant where the failure happened. Fine as a source
for the schema; say which machine.

## 2. The access token lives 8 hours, not 1

```
  file written : 2026-08-09T15:25:48Z
  expiresAt    : 2026-08-09T23:25:48Z
  difference   : 7:59:59.99
```

⚠ **`BUILD-32-FINDINGS` §1 and §2.4 say "exactly 1 hour (3,600 s)".** That was
derived by assuming a one-hour lifetime and subtracting it from `expiresAt` to
get an "issuance" time — a circular step reported as a measurement. Measured
against the file's mtime it is **8 hours**.

The conclusion that copies "are guaranteed to go stale within 1 hour" is wrong by
a factor of eight, and the correct number fits the incident better: the office
ran most of a working day before it died.

## 3. The strongest evidence for rotation is a timestamp nobody cited

```
  source credentials rewritten : 15:25:48Z   ← a refresh happened here
  live session died            : ~15:30Z
```

⚠ **Four minutes apart.** The source account refreshed, and the agent running on
a copy stopped working immediately after. That is real evidence for the rotation
hypothesis, and it is in the file rather than in the OAuth spec.

## 4. What is still not measured

`BUILD-32-FINDINGS` §2.1–2.3 state that Anthropic enforces refresh-token
rotation, that the old token is invalidated, and that a stale copy is refused
with `400 invalid_grant`. **No before/after value was recorded and no rejection
was observed.** RFC 6749 says what the standard permits, not what this server
does.

⚠ **That is the build's own hypothesis returned as its finding.** The spec asked
for observations *"even if they contradict the hypothesis"*, and every answer
agreed with it.

⚠ **The copy half cannot be tested safely right now.** If rotation is real,
copying live credentials into a test profile and refreshing there would
invalidate the account the office itself uses.

## 5. The cheap, safe measurement — in flight

Rotation is decidable by watching one value across a natural refresh. Recorded
before, no forcing, nothing copied:

```
  observed_at  : 2026-08-09T22:13:57Z
  refresh_sha  : 350083d0da90fad9      (sha256, first 16)
  access_sha   : 3b23cad5558961a0
  next refresh : at expiry, 23:25:48Z
```

**After the next refresh, re-hash.** A changed `refresh_sha` proves rotation and
settles the build. Unchanged proves the mechanism is something else, and the
decision needs revisiting.

## 6. Status of the decision

"Agents on one account share one config dir" is **provisional**. It is probably
right and §3 supports it, but it is a structural change resting on an
unmeasured mechanism. Do not close the `TODO` entry as understood until §5 is read.

⚠ **Separately: the lab tenant has no claude credentials at all.** `architect`
shows `Not logged in · Run /login`. The rebuild took them, so the office there is
not currently usable.
