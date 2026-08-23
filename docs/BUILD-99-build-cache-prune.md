# Build 99 — reclaim the build cache, and nothing else

**Base: `main` at `d9a5d16`.** Small, destructive, on a shared host. Named and
reported, same discipline as build 85's networks.

## What, and why only this

Measured by you at build 98:

```
Images         172 total, 8 active     20.23 GB   15.85 GB reclaimable (78%)
Build Cache    213 entries, 0 active    9.89 GB    5.58 GB reclaimable
Disk           82% used, 18 GB free    (79% at build 84's baseline)
```

⚠ **Prune the BUILD CACHE only.** `docker builder prune -f` — no `-a`, no
`system prune`, no image prune.

**Why the cache and not the images**: the cache reports **zero active entries**,
and its worst case is that another lane's next build is slower. **164 of 172
images are inactive and I cannot tell from here which a lane still wants** — that
is a decision needing an owner, not a reclaim.

⚠ **The cache grew from 170 entries / 7.87 GB at build 84 to 213 / 9.89 GB
today.** One day. Record the reclaimed figure against the 5.58 GB predicted:
**if they disagree, that gap is more interesting than the space**, because it
means `docker system df` is not describing what prune does.

## Report

- `docker system df` and `df -h /` **before and after**
- the exact command run
- reclaimed vs predicted
- ⚠ **confirm the 39 running containers are untouched** — a build cache prune
  should not affect a running container, and confirming it is how we know we ran
  what we thought we ran

⚠ **Stop and report if the prune wants to remove anything other than build
cache.** Do not answer a prompt to widen it.

⚠ **Nothing else.** No images, no volumes, no networks, no processes, no other
lanes' clones.
