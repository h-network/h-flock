# Build 89 — acceptance after build 87

**Base: `main` at `1212fa7`.** Same procedure as
[`BUILD-86-baseline-acceptance.md`](BUILD-86-baseline-acceptance.md) — that file
is still the method; this one only says what changed and what to watch.

⚠ **The baseline was `0` at `940c809`.** Exactly one build has merged since. If
this run is not also `0`, the cause is in that delta, which is the whole reason
we took a baseline before starting sprint work.

## What changed

Build 87 rewrote how `office send` parses its arguments. `argparse.REMAINDER` is
gone from the `send` path. The contract is now:

```
office send -a NAME "one quoted argument"
office send -a NAME --stdin          # body on stdin
office send -a NAME --file PATH      # body from a file
office send --agent=NAME "…"         # the equals form now works
office send -a NAME -- --leading-dash-body
```

The acknowledgement changed too: `sent to NAME: N bytes (STREAM_ID)` instead of a
bare stream id.

## ⚠ What to watch, specifically

**`container/plumbing-check.sh` calls `office send` three times with an unquoted
shell variable** — lines 131, 160, 170. All three markers are single tokens with
no spaces, so they should still pass as one positional argument. **I checked this
by reading. You are checking it by running, which is the point.** If any of the
three agent-message gates fails, that is the first place to look and it is a
regression in 87, not in the harness.

⚠ **An unquoted multi-word send now fails loudly** rather than silently sending
the first word. If you see an argparse error from `office send` anywhere in the
run, that is a *caller* that needs quoting — report the caller, do not fix it.

**`container/scenarios/soak.sh` quotes its body**, so it is expected to be fine.
Confirm rather than assume if the run touches it.

## Everything else is BUILD-86

Same host, same one-fresh-tenant rule, same `PATH=~/pw-venv/bin:$PATH`, same
teardown, same report shape, same rule that you do not fix what you find.

⚠ **Capture `EXIT:$?` into the log this time**, as you proposed after build 86 —
so the exit code is read from the process rather than argued from the output.

⚠ **Re-check that no network survives teardown.** Build 86 showed `accept.sh`
cleans up correctly; that is now a property worth re-confirming rather than
assuming, since it is the only evidence we have that the harness is not the
source of the stranded networks.
