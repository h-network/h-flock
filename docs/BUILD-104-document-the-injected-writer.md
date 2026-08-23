# Build 104 — say what `writer: fault-injection` means

**Lane: `api`. Base: `main` at `c2e4a96`.** Branch from main, push to origin.

⚠ **Small on purpose.** A doc audit after builds 95–103 found almost nothing
stale — the lanes documented their own work inside their builds, which is the
habit your build 93's two refusals produced. **This is the one real gap.**

## The gap

`docs/CONTRACTS.md:262` defines `writer` generically and the document lists
`control`, `switch`, `port`, `tmuxhost`, `watchdog`, `container` and `usage`.

**It does not list `fault-injection`** — the one value that means **"this record
was deliberately injected and does not represent real operation."**

⚠ **Why that matters more than it looks.** Build 100 puts a genuine
`forward_unknown` in a custody log, and build 102 a genuine
`stop_agent_incomplete`. Both are real records of things that really happened —
**to a tenant that was deliberately broken.** A reader who does not know the
value exists will either treat an injected record as a live incident, or, worse,
learn to dismiss records carrying an unfamiliar writer.

**Document it: what it is, that it is set by the scenarios in
`container/scenarios/`, and that it never appears in normal operation.**

## ⚠ The control — and this is the first build to use `bus`'s carve-out

*"`writer: fault-injection` never appears in normal operation"* is a **STRUCTURAL
claim**, not a behavioural one: it is a property of the source, that no shipped
code path sets that value. `docs/TEST-SIGNOFF.md` permits inspection for
structural claims **under two conditions**, and you must meet both:

1. **Name it as a structural claim in the sign-off**, so a reader knows which
   kind it is.
2. **Mutate the structure and show the checker fails** — add a `FLOCK_WRITER`
   assignment somewhere in `src/` and prove the check goes red.

⚠ **Do not manufacture a runtime test for it.** It would assert something
adjacent — that some particular path does not emit it — and pass while the claim
is false elsewhere. That is the failure `bus`'s narrowing exists to prevent.

## Also in scope

`BUILD-CONVENTION.md` §3.0 does not say that `--keep` transfers the console
process to the operator. **The `kept:` line says it; the convention does not**,
and the convention is what someone reads before a run.

## Out of scope, considered and excluded

`container/scenarios/reconcile-unicast.py` and `reconcile-broadcast.py` appear
only in `BUILD-*` and `TODO.md`. **Leave them.** They are scenario tooling, not a
contract, and adding them to a living document would create a maintenance
obligation for something that changes with each scenario.

## Done means

Pushed. Tests green. `TEST-SIGNOFF`, verifier assigned by me. ⚠ **Merged-tree
check required** — `CONTRACTS.md` is a living document.
