# Build 86 — the baseline acceptance run

**Base: `main` at `9fdffbe`.** This is the first real acceptance run this office
has commissioned, and the first one nobody involved in writing the code is
performing.

⚠ **The question is not "does it pass".** It is: **do we actually have a good
running version, or do we only think we do?** Nothing after this depends on a
guess. Sprint work starts once this number exists, so that any later failure is
attributable to the sprint rather than to something that was already broken.

⚠ **A `100` is a real and acceptable answer. So is a failure.** Do not tune
anything to get a green. If it fails, the run succeeded at its job.

## Get the repository onto the lab

⚠ **Use your own directory.** Sixteen old clones exist under `/home/h-lab/*/`
from past builds — those belong to other lanes and the newest is at `8067cfa`,
well behind. Do not reuse one.

```bash
mkdir -p ~/acceptance && cd ~/acceptance
git clone git@github.com:h-network/h-flock.git || (cd h-flock && git checkout main && git pull)
git -C ~/acceptance/h-flock rev-parse --short HEAD    # record this
```

## Before you start, record the host

Both of these go in the report — `BUILD-CONVENTION.md` §3.0a and §3.0:

```bash
grep '^FROM' container/Dockerfile     # base image digest; a run is host AND image
free -h                               # you predicted memory is the top risk
df -h /
```

⚠ **Check the three ports are free before you run**, because 39 containers from
other lanes are on this host. Defaults are `--api-port 8080`, `--session-port
8081`, `--console-port 8099`. If any is taken, choose others and **say which you
used** — the mapping is part of the evidence.

## The run

```bash
cd ~/acceptance/h-flock
PATH=~/pw-venv/bin:$PATH bash container/accept.sh --tenant <yours>
```

⚠ **`PATH=~/pw-venv/bin:$PATH` is not optional.** You proved that venv launches
chromium and renders a page. This is likely the first acceptance run in weeks
that genuinely exercises the console flows rather than skipping them, so if they
fail, that failure is *news* and not necessarily a regression.

⚠ **Everything it prints is evidence, including the dull parts.** The script says
so itself. Capture the whole run to a file on the lab — an SSH detach has cost
one run's evidence before — and quote from the file, not from memory.

## ⚠ Then check whether our own harness strands a network

This is the part I most want to know, and it is new:

```bash
docker network ls | grep <your-tenant>
```

`accept.sh` tears the tenant down itself. **If a network named for your tenant
survives that teardown, our acceptance harness is doing the exact thing build 85
just cleaned up after** — and that would explain where some of those four came
from. Report either answer; "no network survived" is a genuinely useful result.

Also confirm the container count is back to what it was before you started.

## Report

Per `BUILD-83-acceptance-seat.md`. First word is the **exit code as a number**.
Then:

- the commit you tested and the base image digest
- `free -h` and `df -h` from before the run
- the ports you used
- **what did not run**, named
- every failure: the command, the output pasted, and the file it points at
- whether a network survived teardown
- your judgement: is this a version we can build on?

⚠ **You do not fix anything.** If you find a defect, that is the deliverable.
