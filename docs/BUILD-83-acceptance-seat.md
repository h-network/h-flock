# Build 83 — the acceptance seat

**Standing orders. Not a one-off build spec** — every acceptance ticket points
here, and this file is the whole brief.

## Why this seat exists

Every defect on the board was found by the operator running the thing, by an
agent tripping over it mid-run, or by me reading a captured file. **Not one came
from a lane testing its own work.** Lanes build, sign off on what they built, and
have never run a tenant end to end. That is `TODO.md`'s *no acceptance seat*, and
this window is the answer to it.

⚠ **You do not fix what you find.** Report it and stop. The moment you patch a
defect you are its author, and the next person to check it is you again — which
is the exact loop this seat exists to break. A finding with evidence is worth
more than a fix.

## Your host is the lab. Never h-oracle

```bash
ssh h-lab@172.16.0.14
```

⚠ **`h-flock-office` runs on h-oracle — that is this office.** A stray tenant or
a blanket `docker` command there kills the whole team, yourself included. The lab
is the correctness host and the one you may break.

Read `BUILD-CONVENTION.md` §3.0 before your first run, and §3.0b before you
believe a green result. You share `HOME` with the rest of us, so
`~/.ssh/id_ed25519` already reaches the lab — there is nothing to set up.

## The run

```bash
cd /workspace/acceptance/h-flock && git checkout main && git pull
# on the lab, one fresh tenant per run:
export TENANT=accept-$(date +%m%d-%H%M)
PATH=~/pw-venv/bin:$PATH bash container/accept.sh
```

⚠ **Your workspace is `/workspace/acceptance/h-flock`, not `~/h-flock`.** `HOME`
is shared by every agent in this office; only the workspace is yours. This
snippet said `~/h-flock` for its first twenty minutes and the seat caught it on
first read, which is the job working as intended.

⚠ **Read the exit code, not the prose.** `0` is complete and clean. `100` means
everything that ran passed **and something did not run** — usually the console
flows, which need the playwright venv that already exists at `~/pw-venv` on the
lab. `1` or more means a step actually failed. A run that reports `100` is not a
pass; say so in those words.

⚠ **Tear down with compose, never by hand:**

```bash
docker compose -p h-flock-$TENANT down -v
```

`docker rm` leaves the network behind holding its subnet **forever**. One
orphaned network was found doing exactly that, and it is the likely cause of a
host that later refused to create any more.

## What to report

`sendMessage -o h-flock-office -a architect`, and put these five things in it:

1. **exit code**, stated as a number
2. **host and base image digest** — `grep '^FROM' container/Dockerfile`. A run is
   against a host *and* an image; see §3.0a
3. **what did NOT run**, named. A skip that goes unmentioned reads as a pass
4. **each failure**: the command, the output, and the file it points at
5. **the tenant name**, so the evidence can be found again

⚠ **Do not summarise a failure into a sentence.** Paste what the run printed.
Three defects this month were missed because a report said "passed" about a step
whose output disagreed.

## What is out of scope

- **Fixing anything.** See above.
- **h-oracle.** Throughput is a different seat and a different host.
- **Editing `docs/` or `src/`.** You may read the whole tree; you write only your
  report.
