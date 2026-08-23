# Build 89 — acceptance after build 87

**Exit code `0`, read from the process.** `main` at `19ad5c1` (build 87 at
`1212fa7`), on `h-lab@172.16.0.14`, base image
`ghcr.io/h-network/base@sha256:10406097c895…` — **the same digest as build 86**,
so host and image are both held constant and the delta really is the code.

⚠ **The baseline held.** `0` at `940c809`, `0` at `19ad5c1`, one build in
between. That is the whole reason the baseline was taken before sprint work
started.

| | |
|---|---|
| plumbing check | **26 / 26** |
| failure simulator | **19 / 19** |
| console flows | **4 / 4** |
| skipped | nothing — no `⚠ NOT CHECKED` in the log |
| teardown | network removed, counts restored to 39 running / 41 total / 8 networks |

## The build-87 risk came back clean

`container/plumbing-check.sh` calls `office send` three times with an unquoted
shell variable (lines 131, 160, 170). I predicted by **reading** that all three
markers are single tokens and would still parse as one positional argument. The
run confirmed it by **executing**: all three gates inside the 26 passed, and a
case-insensitive grep of the whole log for `error|usage:|unrecognized|argparse|
traceback` returned **zero matches** — so `argparse` rejected nothing anywhere.

⚠ **`container/scenarios/soak.sh` was NOT exercised**, because `accept.sh` does
not call it. Its body is quoted and should therefore be fine, but **this run
cannot confirm that**, and the seat recorded the gap rather than letting the
prediction stand as verified. That distinction is the job.

## Method improved from build 86

- **`EXIT:$?` appended to the log** — the exit code is now read from the process
  rather than argued from the presence and absence of summary lines
- **networks counted with `docker network ls -q`**, not the header-inflated form
  that produced 9 for 8 in build 86
- **`accept.sh`'s teardown re-confirmed rather than assumed** from build 86 — it
  again stranded nothing, which is the only evidence we have that the harness is
  not the source of the four networks build 85 cleaned off this host

⚠ **Still not covered: build 88.** `main` has since moved to `60ba4dd`, which
merged the watchdog and `office usage` changes. This run predates them.
