# Build 122 — verify script 2 against its spec

**Lane: `acceptance`. Base: `bus/build-120-script-2` at its head** — ⚠ **not
`main`.** Confirm the tip with `bus` and **name it in your signoff**.
⚠ **Host: the lab.** Correctness. **Do not quote a rate.**

⚠ **Verify against `BUILD-120`, the spec.** `BUILD-120-results.md` is `bus`'s
account of meeting it — **a claim to check, not a description to confirm.**

## ⚠⚠ Context you need, because it changes what you should distrust

**Script 2 found seven defects in itself before reaching you**, and **every one
was the ack wait and the judge disagreeing** — on measure, on null handling, on
error tolerance, on code path, on input file, on scope. The fabric behaviour was
proven early and never in doubt. **The accounting was the whole problem.**

⚠ **So distrust the accounting, not the round trip.**

## The five checks

**1 — the seven controls actually fire.** `tests/test_payload_ack_judge.py`.
⚠ **Run them, and satisfy yourself each asserts the exact REASON and the process
EXIT CODE**, not merely that `rc=N` appeared in stdout. Two controls share `rc3`
(`ack_for_unsent`, `ack_missing_correlation`) — ⚠ **confirm the test can tell
them apart.**

**2 — ⚠⚠ THE THREE-WAY AMBIGUITY, WHICH IS WHY THIS SCRIPT EXISTS.** Build a
fixture for each and confirm **three different verdicts**:

| condition | must return |
|---|---|
| payload never landed | `rc1 payload_never_landed` |
| landed, receiver never acked | `rc2 payload_landed_ack_not_sent` |
| acked, origin never saw it | `rc5 ack_leg_unknown` |

⚠ **If any two collapse into one verdict, the script is worth little** — that
distinction is the entire argument for building it over script 1 plus a checksum.

**3 — a clean live run.** Against a tenant **carrying other traffic**.
**`rc0`, and `ignored_out_of_scope` NON-ZERO.** ⚠ **An idle tenant proves nothing
about the scoping** — that is the defect that took three attempts to fix.

**4 — ⚠ the timeout is non-fatal, and it has NEVER been exercised.** Landed at
`d00d7a9` an hour ago. **Force the ack wait to time out** — a very short deadline,
or a receiver that does not ack — and confirm the run **does not exit at the
wait**, that `PAYLOAD_WAIT reason=…timeout` is emitted, and that **the judge still
runs on a fresh capture and returns its own verdict.**

**5 — diagnostics.** On any non-zero: `status=complete`, six artifacts, sha
manifest, `API_TOKEN=REDACTED`.

## Out of scope

⚠ **Do not fix what you find — report it.** ⚠ **Do not wire anything into
`accept.sh`.** ⚠ **Do not touch script 1** — it was proven live in `BUILD-121`.

## ⚠ Two things that will cost you a cycle if nobody tells you

**The tenant procedure is yours** — detached, stdin closed, poll the log. ⚠ **A
stray VOLUME under the project label triggers `accept.sh`'s exit 2 even with no
container left.** `bus` lost most of a day to this. **Write the procedure into
your results doc this time.**

## Done means

Pushed. `TEST-SIGNOFF` naming the branch head, host and digest. ⚠ **State plainly
in one sentence whether script 2 is trustworthy.** ⚠ **Scan evidence for secrets
before pushing.**
