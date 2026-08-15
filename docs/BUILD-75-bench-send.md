# Build 75 — `bench-send.py`: the traffic generator should be a file

> **Base on `main`.** Branch `tmux/build-75-bench-send`, push to origin.
> Owner: `tmux` (`container/scenarios/` only — **no product code**).

## 1. What is wrong

The receiver is a documented 91-line file (`bench-port.py`). The **sender is an
inline heredoc pasted into four shell scripts** — `base-run.sh:46`,
`base-run-tmux.sh:49`, `fabric-bench.sh:56`, `switch-bench.sh:84` — and nothing
in `tests/` references any scenario script.

Three recurring costs, all one root cause:

- ⚠ **The `-i` trap has to be remembered four times.** `docker exec` without
  `-i` makes Python read an empty program and **exit 0** — a clean-looking run
  that produced nothing. It has bitten **five times**, most recently in build
  74's source-stamp control.
- ⚠ **The `sent`-capture workaround is duplicated four times.** The generator
  runs under `docker exec`, so its records never reach `docker logs`; each script
  separately remembers to append `$SEND_LOG` afterwards (`base-run.sh:77`). When
  one did not, `sent -> popped` read **n=100 of 2,000** and was quoted as a
  result.
- **No payload-size knob**, so build 72 could not add one in a single place.

## 2. Build `container/scenarios/bench-send.py`

Mirror `bench-port.py`: a real file, a docstring saying what it is and is not,
`docker cp`'d in exactly as `switch-bench.sh:69` already does for the port.

```
--pod --tenant --prefix --count --rounds --payload-bytes
```

⚠ **`--payload-bytes` defaults to today's `{"text": "r{rnd}"}`.** It pads, it
does not replace — the default run must be byte-identical to the current one.

## 3. ⚠ Fix the capture properly, do not centralise the workaround

`bench-port.py` already solves this: `switch-bench.sh:70` runs it with
`>>/proc/1/fd/1`, so its records reach PID 1 and appear in `docker logs`
natively.

**Do the same for the sender**, and then **delete the `grep '^{' "$SEND_LOG" >>
"$OUT"` lines** from the scripts. ⚠ **The workaround should disappear, not move.**

Safe because `bus/logging.py:88` writes each record with a single `write()` below
`PIPE_BUF`, which is atomic against peer writers — that comment exists for
exactly this case.

⚠ If for any reason `/proc/1/fd/1` does not work here, **say so and keep the
append** rather than inventing a third mechanism.

## 4. ⚠ The gate: the traffic must not change

This is a refactor of the harness. **Every historical comparison depends on the
default run being the same run.**

- same ring topology (`bench-i -> bench-(i%n)+1`), same default payload, same
  ordering
- ⚠ **paired before/after on the SAME host, same session**, `switch-bench.sh` and
  `base-run.sh`: identical envelope counts and identical six-stage coverage
- ⚠ **if any stage count moves, stop and report it.** A harness refactor that
  changes the numbers has changed the experiment

## 5. Done when

- all four scripts call `bench-send.py`; **no heredoc generator remains**
- `$SEND_LOG` append removed, or §3's exception invoked with a reason
- paired before/after shows identical counts and coverage
- `python3 -m pytest -q` green (388 at the time of writing)
- `container/accept.sh` green
- fresh tenant, `down -v`, ⚠ **lab only — this is correctness, not performance**

## 6. Reporting

`jira done`, then message `architect` with the before/after count and coverage
tables, confirmation that no heredoc generator remains, and whether the
`$SEND_LOG` append is gone or why it had to stay.
