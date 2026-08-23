# Build 86 — baseline acceptance results

**Exit code `0`.** `main` at `940c809`, on `h-lab@172.16.0.14`, base image
`ghcr.io/h-network/base@sha256:10406097c895…`, tenant
`accept-baseline-0823-1618`, 2026-08-23.

⚠ **This is the reference point.** Any acceptance failure after this date is
attributable to what changed since, because this run establishes that the tree
was clean before sprint work started. Run by the acceptance seat — **the first
acceptance in this repository performed by someone who wrote none of the code.**

| | |
|---|---|
| plumbing check | **26 / 26**, 0 failed |
| failure simulator | **19 / 19**, 0 failed |
| console flows | **4 / 4** — hire reaches terminals, closed tab stays closed, retired agent's tab disappears, typed input survives a refresh |
| skipped | **nothing.** No `⚠ NOT CHECKED` line anywhere in the log |
| host before | 1.2 GiB free of 7.8, swap already 1.6/2.9 in use, 20 GB disk free |

⚠ **The console flows genuinely ran.** §3.0b's venv was verified by launching
chromium and rendering a page in build 84, not by testing for the binary — so
this is the first acceptance in weeks that exercised the console rather than
skipping it and exiting 100.

## ⚠ `accept.sh` does not strand a network

The question build 85 raised, now answered. The teardown logged
`Network h-flock-accept-baseline-0823-1618_default Removed`, and
`docker network ls` after the run showed nothing tenant-shaped. Container and
network counts returned to exactly what they were before: 39 running, 41 total,
8 networks.

**So the four stranded networks cleaned off the lab in build 85 did not come from
a clean acceptance run.** They came from an interrupted one or from a manual
`docker rm` — which leaves the `BUILD-CONVENTION.md` §3.0 teardown rule correct
and pointed at the right cause.

## On how the exit code was established

The run was backgrounded over SSH and `$?` was not captured, which the seat
flagged itself rather than presenting `0` as read. It then argued from the
**absence** of the two failure markers.

⚠ **That form of argument has a hole**: a process killed mid-run — OOM being the
seat's own predicted risk on this host — leaves neither marker present and exits
`137`. The sound proof was already in the log and is **presence plus
completion**: `accept.sh` prints `passed: install, health, plumbing, simulator,
console reachable` **only** when `FAILED` is `0`, and the log continues to the
teardown block, which cannot be reached by a process that died early.

**Future runs capture `EXIT:$?` into the log** so neither argument is needed.

## The standing risk is the host, not the tree

1.2 GiB free with swap already active **before** the build started. It did not
bite this time. It is the most likely cause of a future failure on this box, and
it is not a defect in h-flock — see `BUILD-CONVENTION.md` §3.0.
