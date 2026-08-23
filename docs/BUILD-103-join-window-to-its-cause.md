# Build 103 — make `window_created` say which hire caused it

**Lane: `tmux`. Base: `main` at `65a28be`.** Branch from main, push to origin.

Closes the open half of *a hire leaves no record of whether it worked* — the row
that produced build 91's five refusals and was only ever half-delivered.

## Where this actually stands

⚠ **The row shrank once on measurement and then grew again on inspection.** It
originally assumed `tmuxhost` needed a whole new confirmation record. It does not
— `src/flock/tmuxhost/host.py:116` and `src/flock/tmuxhost/host.py:150` **already
emit `window_created`**, which `acceptance` found while measuring the gap at
**4.091 s** on a live tenant.

⚠ **But there is no `correlation_id` to thread.** `tmuxhost` reconciles from
Redis desired state, and `start_agent` **never persists one**. So this is not
plumbing an existing value through — it is **new desired state**, and it has a
lifecycle.

## The three questions this build has to answer

**1. Where does the id live between the control write and the reconcile?**
It has to survive the gap and be findable by a component that never saw the
envelope.

**2. When is it cleared?** ⚠ **A stale id is worse than none** — it would attach
a window to a hire that did not cause it, and every custody join downstream would
inherit that lie. Say what clears it and prove it.

**3. What does `window_created` emit when there IS no cause?** ⚠ **This is the
case that makes it interesting.** `tmuxhost` rebuilds missing windows on
reconcile with **no control envelope behind them at all** — a crash recovery, an
`__init__` placeholder. **Those events must remain valid and must not borrow
somebody else's id.** An absent correlation is a fact; make it read as one.

## Constraints

⚠ **Control must NOT wait for the window.** You argued this during build 91 and
you were right: waiting turns an asynchronous architecture into a gate, and
window presence does not prove correct configuration. `_accepted` keeps its
current meaning.

⚠ **The gap is 4.091 s, measured, not assumed.** Whatever you build tolerates it,
and a join that only works when reconcile is fast is not a join.

## What this buys

`start_agent_accepted` and `window_created` become joinable, so *"did that hire
work?"* is answerable **from the log** rather than by attaching to a pane — which
is what the original row asked for and what build 91 could only half-deliver.

## Done means

Pushed. Tests green. `TEST-SIGNOFF`, verifier assigned by me. ⚠ **Behavioural
claims need executing controls.** ⚠ **Merged-tree check required** if you touch a
living contract — `CONTRACTS.md` describes the control records and will need the
join described.
