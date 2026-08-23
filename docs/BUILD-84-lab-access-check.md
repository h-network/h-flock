# Build 84 — can the acceptance seat actually work on the lab?

**Base: `main` at `2aac76f`.** Start from main, pull before you begin.

⚠ **This is a capability check, NOT an acceptance run.** Do not build an image,
do not start a tenant, do not execute `container/accept.sh`. The deliverable is a
report saying whether the seat *could* run — and naming precisely what is missing
if it could not.

The seat was created today and has never touched the lab. Everything below is
assumed to work and none of it has been tested from this office.

## The host

```bash
ssh h-lab@172.16.0.14
```

You share `HOME` with the rest of the office, so `~/.ssh/id_ed25519` should
already reach it. **If it does not, stop and report that** — it is the first
thing that has to be true and nothing else matters until it is.

⚠ **`h-cli` on the lab is not ours. Do not stop it, remove it, or prune
anything.** Read-only inspection only, this whole ticket.

## What to establish, in this order

1. **SSH** — you land on the lab, and `whoami` / `hostname` say what you expect.
2. **Docker** — `docker ps` runs without sudo, and `docker --version` and
   `docker compose version` both answer. Note whether compose is the plugin
   (`docker compose`) or the old standalone binary; the teardown command in
   `BUILD-83-acceptance-seat.md` assumes the plugin.
3. **What is already running** — list containers and networks. Name anything
   h-flock-shaped that is left over from an earlier run, and any network with no
   container attached. ⚠ **Report them, do not remove them.** A stranded network
   holds its subnet forever and is worth knowing about; deleting one is a
   separate decision.
4. **Room to work** — free disk and free memory. It is a 4-vCPU, 7 GB VM and an
   image build is the heaviest thing it does.
5. **The repository** — can you get h-flock onto the lab at all? ⚠ **Do not
   assume the lab can reach GitHub.** Your key lives in this container, not on
   that host. If there is already a clone, say where and what commit it is on. If
   there is not, find out what a clone would need and report that rather than
   solving it.
6. **The playwright venv** — `BUILD-CONVENTION.md` §3.0b says it exists at
   `~/pw-venv` on the lab. Verify it, and verify `playwright` actually runs from
   it. ⚠ **This is the single most load-bearing item here**: without it the
   console flows skip, and a skip used to read as a pass for weeks.

## Report

`sendMessage -a architect`, with a **yes or no** as the first word: could you run
acceptance on that host today?

Then, for each of the six items: what you ran, what it said, and pass or fail.
Paste the output for anything that failed — do not summarise it into a sentence.

Finish with the one thing most likely to break a real run, in your judgement.
That is the part I cannot get from a checklist.
