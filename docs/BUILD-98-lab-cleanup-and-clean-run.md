# Build 98 — clear our own leaks off the lab, then a clean run

**Base: `main` at `01f97e5`.** Method is
[`BUILD-86-baseline-acceptance.md`](BUILD-86-baseline-acceptance.md).

⚠ **You diagnosed the mess this cleans up.** Both processes are h-flock's own
console proxies, leaked by `container/accept.sh:83` returning from `cleanup()` on
`--keep` before it reaches the `kill`.

## Part 1 — remove exactly two processes

```
PID 2790629   port 8099   running 4h+    from BUILD-90
PID 2838728   port 8199   running 1h+    from BUILD-94
```

Both are `python3 server.py --listen 0.0.0.0 --port <N> …`, both `PPID 1`.

⚠⚠ **VERIFY THE COMMAND LINE IMMEDIATELY BEFORE KILLING EACH ONE.** A PID is not
a name — these have been running for hours, and if either has already exited its
number may belong to something else entirely. Read `/proc/<pid>/cmdline`, confirm
it is `server.py` with the expected port, **then** kill. If it does not match,
**stop and report**; do not hunt for a replacement PID.

⚠ **Kill only these two.** No `pkill` by pattern — `accept.sh` carries a comment
recording that a host-wide `pkill` once killed unrelated SSH shells whose command
line happened to match. That comment is in the file you are cleaning up after.

⚠ **Nothing else on that host is yours to remove.** Not containers, not networks,
not images, not the build cache, not other lanes' clones. **Report disk and
`docker system df`** — it has moved 79% → 82% across today's runs and the trend
is worth a number — **but prune nothing.** That is a separate decision and it is
not yours or mine to take unilaterally.

## Part 2 — a clean acceptance run

Full run on current `main`, `--keep` **NOT** set unless you need it. If you do set
it, ⚠ **you now own the console process too** — that is the whole finding.

Per `BUILD-CONVENTION` §3.0: record `free -h` and `df -h /`, and if a default port
is unavailable, **name what holds it** before working around it. With both
orphans gone, `8099` should be free for the first time since build 90 —
**confirm that, because it is the proof the cleanup worked.**

## Report

Two verdicts. For part 1: the cmdline you verified for each PID, and the port
state after. For part 2: per `BUILD-83-acceptance-seat.md`.

⚠ **Hash the run log and push the significant evidence**, as you did for build 97.
