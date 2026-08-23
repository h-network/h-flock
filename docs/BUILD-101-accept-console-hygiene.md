# Build 101 — stop leaking the console, stop putting credentials in `ps`

**Lane: `tmux`. Base: `main` at `6c29b63`.** Branch from main, push to origin.

Two defects, one file: `container/accept.sh`. ⚠ **Neither needs `clients/` to be
touched**, which matters because that directory is closed to development.

## 1. `--keep` leaks the console proxy forever

`container/accept.sh:83` returns from `cleanup()` when `KEEP=1`, **before**
reaching line 87's `kill "$CONSOLE_PID"`. The console is a **host process**, so
`docker compose down -v` never reaches it: an operator tears the tenant down
correctly and the console survives indefinitely.

**Measured**: two orphans were found alive at **4 h and 1 h**, from builds 90 and
94, holding the harness's own default port and its fallback. Build 98 confirmed
the boundary — a run *without* `--keep` cleans up correctly, so this is
`--keep`-specific.

⚠ **Do not simply kill it on `--keep`.** `--keep` exists so an operator can work
on a live tenant, and **the console is part of what they kept.** The defect is
that ownership transfers *silently*. **The `kept:` line must name everything the
operator now owns** — the container **and** the console PID, with the command to
stop it. If you conclude killing it is right after all, argue that instead;
either answer is acceptable, an unstated transfer is not.

## 2. The token and secret are passed as command-line flags

`container/accept.sh:200` launches the console with `--token <TOKEN> --secret
<SECRET>`. ⚠ **Command lines are world-readable** — both credentials sit in `ps`
and `/proc/<pid>/cmdline` for any user on that host, for the life of the process.
Combined with defect 1, that life was **four hours after the tenant was
destroyed.**

⚠ **`clients/web/server.py:1231` and `:1233` ALREADY default `--token` to
`API_TOKEN` and `--secret` to `HFLOCK_SECRET` from the environment.** The
capability exists and `accept.sh` simply does not use it. **Export them and drop
the flags.** No change to `clients/`, no freeze exception needed.

⚠ **Check the whole launch line for other secrets** before you finish — I found
these two by reading a `ps` output, which is not a systematic method.

## Verification note

`api` verifies this. ⚠ **`acceptance` will then confirm it live after merge** —
it is the primary user of this script and it found both defects. **A grep of
`ps` output during a `--keep` run is the proof for defect 2**, and it is not
something a unit test can give us.

## Done means

Pushed. Tests green. `TEST-SIGNOFF`, verifier assigned. ⚠ **Both claims here are
behavioural.** A test asserting `cleanup()` contains a `kill` proves nothing —
your own rule.
