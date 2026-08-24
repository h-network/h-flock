# Build 107 — make a half-removed agent visible instead of invisible

**Base: `main` at `b06992d`.** Branch from main, push to origin.

⚠ **Two lines of reordering. The damage is already measured and the design was
already argued** — this build applies build 103's insight to build 102's finding.

## What build 102 measured

A fault between the roster `hdel` and the resource purge leaves: `launch`,
`profile`, `provider`, `paused`, `blocked`, `pending.verify`, `tags`,
`delivery.markers` **unpurged**, and the **`delivering` lock held**.

⚠ **The agent does not look broken. It disappears** — `office status` and
`office peers` show nothing, because the roster row is the part that *did* get
removed. ⚠⚠ **And a later `StartAgent` for the same name SUCCEEDS**, republishing
the roster while clearing none of it, so the re-hired agent silently inherits a
`paused` or `blocked` marker and a stuck delivery lock. **Its mail cannot be
delivered.**

## What build 103 established

`tmux` solved the same class of problem by ordering writes inside one Lua call:
**Redis Lua cannot roll back, so the ORDER decides which partial state can
exist.** Roster-first made cause-without-roster impossible — not by cleaning it
up, but by making it unobservable.

## The change

`stop_agent` removes the roster row **first** and purges after, so **the
dangerous partial is exactly the one that happens.**

**Reverse it. Purge the resources first, remove the roster last.**

Then a partial leaves an agent **still in the roster with its state already
cleared** — visible in `office status`, findable, and harmless — instead of
absent-but-contaminated.

⚠ **This is a reordering, not a transaction.** No Lua, no new failure modes. It
does not make the failure impossible; it makes the residue **visible**. That is
the whole claim and the results doc should say exactly that and nothing more.

## ⚠ What to check before assuming it is two lines

- **Does anything depend on the roster row surviving until the purge
  completes?** The purge derives keys from `pod`/`tenant`/`agent`, not from the
  roster, but confirm rather than assume.
- **`port_type` is read before the writes** — check it still is, and that reading
  it does not depend on ordering.
- ⚠ **What does the `_incomplete` reason now say?** The acknowledged subset
  changes when the order changes. That contract cost five refusals; **do not
  weaken it while reordering underneath it.**

## Prove it with the harness that found it

Build 100's injector, extended by build 102, can already fault a control-plane
write. **Inject at the same point and show the residue is now the visible kind.**
⚠ **Same safety properties**: no injection check in `src/`, tenant-bound marker,
`writer: fault-injection`, refusal to arm against a tenant it did not create.

## Done means

Pushed. Tests green. `TEST-SIGNOFF`, verifier assigned by me. ⚠ **Behavioural
claim, executing control.** ⚠ **Bind the capture to the tenant the accepted run
created and fail the build if it is empty or missing what you quote.**
