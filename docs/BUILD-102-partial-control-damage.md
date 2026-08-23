# Build 102 — what does a partial control failure actually leave?

**Lane: `bus`. Base: `main` at `65a28be`.** Branch from main, push to origin.

⚠⚠ **A SPIKE. The deliverable is an ANSWER, not a fix.** Do not write the Lua
script. **"Atomicity is not worth it" is a legitimate and expected outcome**, and
if that is where the evidence points, say so and stop.

## The question

`stop_agent` performs **three** desired-state writes — roster `hdel`, resource
purge, delivery-lock clear — and `start_agent` several, with **no transaction.**
Build 91 made the **record** truthful: `_incomplete`, naming the acknowledged
subset and the write whose outcome is UNKNOWN. **It did not make the failure
impossible**, deliberately, and **nobody has ever seen what one leaves behind.**

## ⚠ The harness needs extending, and that is part of this build

Build 100's injector wraps **`rpush` only**, targets the **ingress** key, and
attaches to the **switch** process. A control-plane fault needs **other Redis
verbs** — `hdel`, `delete`, `set` — and a **different target process**, since
control openers run in the port for `host`.

⚠ **Keep build 100's four safety properties.** They are the reason that build was
accepted: no injection check in `src/`, a marker binding the fault to one tenant,
`writer: fault-injection` on every record, and a refusal to arm against a tenant
it did not create. **Extend the mechanism, do not loosen it.**

## What to report

Inject between the roster `hdel` and the resource purge on a live tenant, then
answer with observations, not inference:

1. **What state survives** — roster row, agent resources, delivery lock, tmux
   window. Name each as present or absent.
2. **What `office status` and `office peers` say** about that agent afterwards.
   ⚠ **This is the operator-visible consequence and the one that decides the
   verdict.**
3. **What a subsequent `StartAgent` for the same name does** — succeeds, fails,
   or produces something worse than either. ⚠ **A silent success onto corrupted
   state is the worst case and the one worth looking for.**
4. **The `_incomplete` record itself, live.** It has never been produced outside
   a unit test. Quote it.

## Then argue the verdict

**With the damage in front of you**, say whether desired-state atomicity is
warranted. The option is a Lua script, as `watchdog/activity.py` already uses for
usage emission.

⚠ **Weigh it honestly.** A mid-sequence Redis failure is rare and the record is
already truthful — so the case for atomicity rests entirely on **how bad the
residue is and how invisible it stays.** If `office status` shows the agent as
plainly broken, the record plus the display may be enough. If it looks healthy,
that is a different answer.

## Done means

Pushed. Tests green. `TEST-SIGNOFF`, verifier assigned by me. ⚠ **Behavioural
claims need executing controls.** ⚠ **Bind the capture to the tenant the accepted
run created, and fail the build if a capture is empty or missing what you
quote** — `docs/TEST-SIGNOFF.md`, added after build 100 committed seven files
containing an error message.
