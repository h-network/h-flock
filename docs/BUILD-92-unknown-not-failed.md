# Build 92 — five records say `failed` where the outcome is UNKNOWN

**Lane: `bus`. Base: `main` at `0d8379a`.** Branch from main, push to origin.

⚠ **You produced the rule this build applies.** `BUILD-91` ruling 11, from four
of your refusals: **acknowledged is a fact, UNKNOWN is an attempt with no reply,
and `failed` is reserved for not attempted or provably rejected.** One test —
**what did the code observe?** An exception is the absence of an answer, never
evidence the thing did not happen.

## The five sites

Each emits a `*_failed` record from an exception handler, over a write that may
have committed and lost its reply:

| | |
|---|---|
| `src/flock/bus/doors.py:86` | `send_failed` — egress write |
| `src/flock/port/openers.py:191` | `board_write_failed` |
| `src/flock/switch/service.py:84` | `kick_failed` |
| `src/flock/switch/service.py:164` | `forward_failed` — broadcast ingress |
| `src/flock/switch/service.py:183` | `forward_failed` — unicast ingress |

⚠ **The two `forward_failed` sites are why this is not cosmetic.** An ingress
write that commits and loses its reply puts the envelope **on the recipient's
queue** while the custody log records it as never forwarded. So conservation
reads a loss that did not happen — and anything responding to that record by
re-sending manufactures a **duplicate delivery**. `HLD` §10 makes at-most-once
the property this design exists to hold and duplicates an absolute defect.

⚠ **`send_failed` reaches the same place through a person.** An agent reads
*"egress write failed"* in its pane and runs the command again.

## ⚠ The contract document asserts the withdrawn inference too

`docs/CONTRACTS.md:318-322` defines the attempt records as *"`send_failed` means
an assembled frame **was not written** to egress; `forward_failed` means a popped
frame **was not written** to ingress; … `kick_failed` means it **could not**."*

⚠ **Fix the prose and the code in the same build.** A doc saying UNKNOWN over
code emitting `failed` is worse than today's state, because the two would
disagree and the doc would look authoritative. **This is why this is not a
documentation sweep.**

## The one decision, which is not mechanical

⚠ **What should conservation do with a forward whose outcome is indeterminate?**
The six-stage join currently expects `forwarded` to be present or absent. A third
state breaks that arithmetic.

**Options, and I am not ruling between them — argue one:**
- count an indeterminate forward as forwarded, and accept a possible phantom
- count it as not forwarded, and accept a possible phantom loss
- carry it as its own bucket so conservation reports *"n indeterminate"* rather
  than folding it into either side

⚠ **State the reasoning in your results doc.** Whichever you choose, a reader of
`office status` or the conservation check must be able to tell an indeterminate
forward from a known one. ⚠ **Do not add retries.** At-most-once is the reason
this matters; a retry is the defect it prevents.

## Also in scope

Document the canonical accounts Redis resource build 91 added — it is declared in
`src/flock/bus/resources.py` and appears in no contract or LLD document.

## Done means

Pushed. Tests green. `TEST-SIGNOFF` filled in, **`VERIFIED BY` is not you** —
I assign the verifier, do not source one. ⚠ **Evidence at an immutable path, and
bind each gate to the FINAL commit**, proving the number reproduces there —
`docs/TEST-SIGNOFF.md` changed today and the pre-results-plus-exclusion dance is
gone.
