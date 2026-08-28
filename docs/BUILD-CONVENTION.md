# How a build spec is written

Short, because the format has worked for 50 builds implicitly. This records the
one rule that was learned expensively, plus the structure already in use.

## 1. ⚠ The rule: a new gate must be shown to FAIL

**Any check a build introduces as its pass criterion must be demonstrated going
red.** Break the thing on purpose, show the gate fail, and put that in the
report. Five minutes per gate.

⚠ **This exists because of four separate incidents on one day, all the same
shape: the green signal was produced by something other than the thing under
test.**

| what looked green | what was actually true | what a negative control would have done |
|---|---|---|
| custody log complete | two records shared a torn line; the parser silently dropped both | write two records concurrently, prove the parser notices |
| 345 tests passing after a rename | passing on `vab = port_type` aliases that hid a half-done rename | delete the alias, prove the suite goes red — **it would not have** |
| web client tests passing | passing against a mock returning the **old** wire shape | point the mock at the real shape, prove the client fails |
| `accept.sh` exit 0, "passed" | `plumbing-check` printed `FAIL=1` and exited 0 | break one check, prove non-zero exit |

⚠ **More tests would have caught none of these.** The failure was never
insufficient coverage — it was gates that could not fail. Spend the effort on
falsifiability, not on volume.

⚠ **A fix for a false-pass that is itself only tested by passing is not proof.**

## 2. The structure that has been working

- **base and branch** named in the first line — `main` unless stated, so a lane
  does not start from whatever it had checked out
- **what is NOT in scope**, explicitly. The most useful section in every spec so
  far, and the one that stops a build growing a router it did not need
- **what would make this a "no"** for a trial or spike, written **before** the
  work, so a negative result is a result and not a failure
- **done when** — the gates, each one falsifiable per §1
- **reporting** — `jira done`, then message `architect` with the commit, the
  evidence, and status

## 3. ⚠ Measurement, if the build claims a number

### 3.0a ⚠ Name the base image digest, not just the host

A run is against a host **and** a base image. `container/Dockerfile` pins
`ghcr.io/h-network/base` **by digest** — the base owns `startAgent` and the agent
CLIs, so it decides how every window launches, and **nothing in this repository
executes `startAgent` or asserts that it works.** The two tests that mention it
check the string we construct, with `run_tmux` mocked.

**Record the digest in any results doc that quotes a number**, the same way §3.0
names the host:

```bash
grep '^FROM' container/Dockerfile          # what the build used
docker buildx imagetools inspect ghcr.io/h-network/base:latest   # what is current
```

⚠ **Every figure taken before 2026-08-22 names no base image** — 845/s, 0 of 40,
the six-stage conservation. All were against
`sha256:74c290e5db49…`, established after the fact, and both hosts happened to
hold the same one. That was luck, not method.

### 3.0b ⚠ Acceptance needs a playwright venv on the lab, or it skips the console

`container/accept.sh` checks the console **flows** — that a hire reaches the
terminals view, that a closed tab stays closed, that typed input survives a
reload. Those need playwright, which is **not** in the tenant image because it
is the operator's tooling, not the product's.

```bash
PATH=~/pw-venv/bin:$PATH bash container/accept.sh
```

⚠ **Without it the run does not fail — it reports `⚠ NOT CHECKED: console-flows`
and now exits 100.** That exit code is the whole point: `1+` means a step failed,
`100` means everything that ran passed and something did not run. It used to exit
`0`, which is how acceptance ran "clean" for weeks on a host with no browser
while checking only that the port answered.

**On `h-lab@172.16.0.14` the venv already exists at `~/pw-venv`.** On a new host,
create it before believing a green acceptance.

### 3.0 ⚠ The two hosts, and which question each answers

We all run as unix user `ubuntu` with a shared `HOME=/home/ubuntu`, so
`~/.ssh/id_ed25519` already reaches both. **Only the username differs, and it is
neither `ubuntu` nor the host name.**

| host | target | what it is | use it for |
|---|---|---|---|
| lab | `ssh h-lab@172.16.0.14` | **4-vCPU QEMU VM**, 7 GB | ⚠ **CORRECTNESS ONLY** |
| perf | `ssh halil@h-oracle` | 32-core Ryzen 9950X3D, 93 GB | ⚠ **PERFORMANCE ONLY** |

⚠ **Never quote a throughput number from the lab.** Identical scripts measured
6.5/s there and **832/s** on h-oracle; `popped -> forwarded` was 7–9 ms there and
**0 ms** here. Build 71 was specified, held and cancelled because an 11 ms kick
turned out to be four-vCPU contention. Every throughput figure in `BUILD-*.md`
older than 2026-08-14 describes the constrained host.

⚠ **The lab is still the better place to find races** — contention surfaces them.
Correctness there, numbers on h-oracle.

⚠ **Do not touch `h-cli` on the lab, or `h-flock-office` on h-oracle** — the
office runs in that container, and killing it kills the whole team. Name your own
tenant and project; one per run, fresh each time.

- **medians, not means.** The lab's loopback Redis averages 1.7 ms with 26 ms
  spikes; a mean measures the spikes
- **interleave A/B per iteration**, or drift measures the drift
- **same container, same run, same method** on both sides. Host-wall against
  inside-container is not a comparison
- **redirect to a lab-local file.** An SSH detach has already cost one run's
  evidence
- ⚠ **`docker exec` output does NOT reach `docker logs`.** `docker logs` shows
  PID 1's streams; a process started by `docker exec` writes to the exec session
  instead. **Records emitted by an exec'd process are invisible to anything
  reading the container log.** Three occurrences: `fabric-bench` reported
  `sent: 54` against `popped: 553`; `bus` flagged it in build 47's evidence and
  declined to present those counts as a custody audit; build 58's duplicate
  control injected a real duplicate that reconciliation then scored as a *loss*.
  ⚠ **A control must travel the same path as the thing it controls for** — do
  not teach the reader about a second evidence source, make the control use the
  first one
- ⚠ **`docker exec` with a heredoc needs `-i`.** Without it the program reads
  empty and exits 0 — silently, successfully, having done nothing. Also three
  occurrences
- **one h-flock tenant at a time** on the lab
- ⚠⚠ **A WORKAROUND YOU DO NOT REPORT MAKES THE PROBLEM INVISIBLE.**
  If a default is unavailable — a port held, a path occupied — **name what holds
  it in your results**, then work around it. Do not just pick another value and
  move on; the next person picks another value too, and nobody ever learns the
  host is accumulating state. ⚠ **This is exactly how four stranded networks
  survived on this host until build 84 went looking**, and it recurred within the
  week: build 94 found port `8099` — `accept.sh`'s own default console port —
  held by an unexplained `python3` process, used `--console-port 8199`, and **the
  process is still there.** The workaround was correct; reporting it is what made
  it a finding instead of folklore.
- ⚠ **`--keep` transfers the console process to the operator.** When
  `container/accept.sh` is invoked with `--keep`, it deliberately preserves both
  the container and the background console proxy host process. The terminal
  output names the transferred process explicitly: `kept: container=<name>; console_pid=<pid> (stop console: kill <pid>)`
  (or `console=not-started`). **The operator who kept the tenant is responsible for
  stopping the host process via `kill <pid>` when done.** Failing to kill it leaves
  orphan proxy processes holding default ports (`8099`) and retaining memory indefinitely.
- ⚠ **`docker system df`'s "reclaimable" over-predicts what the FILESYSTEM gets
  back.** Measured 2026-08-24 on the lab: `docker builder prune -f` reported
  **5.548 GB** reclaimed against **5.578 GB** predicted — those agree, and the
  cache accounting is internally consistent. But `df` moved only **~3.9 GB**
  (82% → 78%). ⚠ **A ~1.6 GB spread at this scale is real, not rounding.**
  **Plausible and NOT verified**: `overlay2` cache layers can share blocks with
  layers still referenced by images left in place, so removing a cache entry's
  accounting does not free that entry's full size in unique blocks. ⚠ **Do not
  plan capacity from `reclaimable`** — treat it as an optimistic ceiling and
  measure `df` before and after. **Docker's number is not wrong about Docker; it
  is not a statement about the disk.**
- ⚠ **Record `free -h` and `df -h /` before every run, in the results.** Not as
  ceremony: **four acceptance runs out of four began with this VM already
  swapping** — 1.2–1.9 GiB free of 7.8, and swap already in use — before a single
  container existed. **A build that dies here is more likely to be the host than
  the code**, and you cannot make that argument afterwards without the number.
  ⚠ **That swapping had a cause, found 2026-08-24: it was OUR litter, not the
  host.** Thirty-five containers from the architect's base-image testing, each
  holding an idle interactive CLI, had been running for 23 hours; two leaked
  console proxies had been running for hours more. After removing them:
  **available memory 4.2 → 7.0 GiB, swap 2.2 GiB → 140 MiB, disk 82% → 71%.**
  ⚠ **The number was worth recording precisely because it turned out to be
  explicable.** A standing "this host is just slow" would have absorbed it
  forever; a measurement repeated four times became a question, and the question
  had an answer.
- ⚠⚠ **TEAR DOWN WITH COMPOSE, NEVER `docker rm`.**
  `docker compose -p h-flock-$TENANT down -v`. Removing containers by hand leaves
  the network behind **holding its subnet forever**, and nothing ever reclaims
  it. ⚠ **This is not hypothetical and it is not one host.** An audit on
  2026-08-23 found **four stranded `h-flock-*_default` networks on the lab** —
  `after`, `mainb`, `nemo`, `vabt`, each with zero containers — plus one on
  another host that is the likely cause of a pool exhaustion reported there. Four
  more stranded networks on the lab belong to other projects, so the habit is not
  ours alone. **Check `docker network ls` after your run**; a network named for
  your tenant that outlives it means you tore down the wrong way
- ⚠ **The lab is SHARED and it is small.** 7.8 GB total, and it has been measured
  at **39 running containers with 1 GB free and swap already in use** before any
  h-flock tenant starts. An image build is the heaviest thing acceptance does.
  **Check `free -h` before a run and say what it was in your results** — a build
  that dies on this host is more likely to be memory than anything in the code,
  and "one tenant at a time" describes h-flock's tenants, not the box's load
- ⚠ **to attribute an INVISIBLE loss, bracket it by FIFO position.** A frame that
  vanished with no records cannot be attributed by its own timestamps — it has
  none. But a per-source queue is FIFO, so the frames **before and after it from
  the same source** bound when it must have been at the head. If an injection
  window falls between those two pops and the frame has no `popped` record, it is
  attributable. `bus` used this on build 66's two vanished frames where
  "sent before a kill" would have proved nothing
- ⚠⚠ **THIS LAB'S THROUGHPUT VARIES BY 35% RUN TO RUN.** Measured on
  main-lineage code the same day: **6.00, 6.40, 6.45, 8.12 /s**. **An unpaired
  throughput comparison on this host establishes nothing below about 35%**, and
  several conclusions have been drawn from smaller differences. Pair every
  throughput claim — same session, back to back — or do not make it
- ⚠ **state the prediction before measuring.** Four claims were retracted in one
  day because a measurement was read as confirming what was expected

## 4. ⚠ Specs are fallible; the base is not

Two spec errors in one day were caught by lanes reading the **base branch**
rather than the prose: `vab` tiered as an internal rename when it is a wire
field, and an allow-list table written in the post-rename vocabulary that would
have broken every current caller.

**A lane that finds the spec contradicts the code should say so and stop, not
implement the spec.** Both catches were worth more than the builds they
interrupted.
