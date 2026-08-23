# Build 85 — remove the four stranded h-flock networks on the lab

**Base: `main` at `0408bd7`.** Pull before you begin.

Your own audit in build 84 found them. This ticket removes exactly those four and
nothing else.

⚠ **The lab is a shared host with 39 running containers belonging to other
lanes.** Everything below is named explicitly for that reason.

## Remove, by name

```
h-flock-after_default
h-flock-mainb_default
h-flock-nemo_default
h-flock-vabt_default
```

**Before each removal, re-check that it still has zero containers attached** —
your audit is an hour old and another lane may have started something:

```bash
docker network inspect <name> --format '{{len .Containers}}'
```

⚠ **If any of them reports anything other than `0`, STOP and report.** A network
that gained a container since the audit means something is running on it, and the
premise of this ticket is wrong for that one.

⚠ **If `docker network rm` refuses with "has active endpoints", STOP and report
that too.** Do not force it. That error means the daemon disagrees with the count
you just read, and which of the two is right matters more than the cleanup.

## Do not touch

| | |
|---|---|
| `h-cli-dev_default` | not ours. `h-cli` on this host belongs to someone else and is explicitly off limits |
| `hvab_default`, `container_default`, `misc-compose-check_default` | stranded, but other projects'. Reporting them was correct; removing them is not yours to decide |
| `hvab-provision-1`, `hvab-logs-init-1` | stopped containers, **exited 0 three days ago**. These are normal compose init containers that ran and finished, not debris. Leave them |
| every running container | all 39 belong to other lanes |

⚠⚠ **NO BLANKET COMMANDS. NOT ONE.** No `docker system prune`, no
`docker network prune`, no `docker image prune`, no `-a` on anything, no
`docker stop $(docker ps -q)`. `docker network prune` would take all eight
stranded networks including four that are not ours, which is precisely the
mistake this ticket exists to clean up after. **Name every object you remove.**

⚠ **Do not prune the build cache**, even though `docker system df` shows it as
reclaimable. Disk is at 79% with 20 GB free, which is enough for an image build,
and pruning it slows every other lane's next build on this host. Not this ticket.

## Record and report

Capture `docker network ls` **before and after**, and diff them. The report
should show that exactly four names disappeared and nothing else changed.

`sendMessage -a architect` with: the four `rm` results, the before/after network
count, anything that made you stop, and confirmation that no running container
changed state.
