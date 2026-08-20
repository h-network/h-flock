#!/usr/bin/env python3
"""cloneToAll — put one repo in every teammate's workspace.

    cloneToAll git@github.com:h-network/h-cli-dev.git
    cloneToAll <url> -a bus,tmux        # only these agents
    cloneToAll <url> --dry-run

Ported from h-office, which read an ``offices.yaml``. Here the roster is the
Redis hash the switch already forwards on, so the agent list is whatever the
tenant says — no need to name anyone.

⚠ **Only ``port_type: tmux`` agents get a clone.** ``api`` and ``control`` have
no window and no ``/workdir`` (``HLD`` §2), so cloning for them would create a
directory nothing can reach.

Each agent gets an independent clone at ``/workdir/<agent>/<repo>`` — own
working tree, own branches, own index.

⚠ **Fetched from the network ONCE.** The first clone is the network one; every
other agent is cloned from that local copy, which git does with hardlinks, and
the remote is then pointed back at the original URL so pushes go where you
expect. N network clones download the same objects N times.

An agent who already has the directory is **skipped, not overwritten** — so
re-running after a new teammate joins only fills the gap.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from flock.bus import members, port_type
from flock.bus import resp as redis

WORKDIR_ROOT = os.environ.get("WORKDIR_ROOT", "/workdir")


def _repo_name(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return tail[:-4] if tail.endswith(".git") else tail


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(prog="cloneToAll", description=__doc__.split("\n")[0])
    ap.add_argument("url", help="repository to clone")
    ap.add_argument("-a", "--agents", default="",
                    help="comma-separated subset; default is every tmux agent")
    ap.add_argument("--dry-run", action="store_true", help="say what would happen")
    args = ap.parse_args(argv)

    pod = os.environ.get("POD", "default")
    tenant = os.environ.get("TENANT", "default")
    try:
        r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
        roster = members(r, pod=pod, tenant=tenant)
    except Exception as exc:
        print(f"error: could not read the roster: {exc}", file=sys.stderr)
        return 2

    if args.agents:
        wanted = [a.strip() for a in args.agents.split(",") if a.strip()]
        unknown = [a for a in wanted if a not in roster]
        if unknown:
            print(f"error: not in this tenant's roster: {', '.join(unknown)}", file=sys.stderr)
            return 2
        agents = wanted
    else:
        agents = sorted(roster)

    # ⚠ Filter AFTER the roster check, so naming an api agent explicitly is a
    # clear refusal rather than a silent skip.
    targets = []
    for agent in agents:
        if port_type(r, pod=pod, tenant=tenant, agent=agent) != "tmux":
            if args.agents:
                print(f"  {agent}: skipped — not a tmux agent, it has no workspace")
            continue
        targets.append(agent)

    if not targets:
        print("no tmux agents to clone into")
        return 0

    repo = _repo_name(args.url)
    todo = [a for a in targets if not os.path.isdir(os.path.join(WORKDIR_ROOT, a, repo))]
    have = [a for a in targets if a not in todo]

    for agent in have:
        print(f"  {agent}: already has {repo} — skipped, not overwritten")
    if not todo:
        return 0
    if args.dry_run:
        for agent in todo:
            print(f"  {agent}: would clone {args.url} -> {WORKDIR_ROOT}/{agent}/{repo}")
        return 0

    # The network clone, once.
    first, rest = todo[0], todo[1:]
    first_path = os.path.join(WORKDIR_ROOT, first, repo)
    os.makedirs(os.path.dirname(first_path), exist_ok=True)
    print(f"  {first}: cloning {args.url} (network)")
    out = _git("clone", args.url, first_path)
    if out.returncode != 0:
        print(f"error: clone failed: {out.stderr.strip()}", file=sys.stderr)
        return 1

    # ⚠ Everyone else is cloned from that local copy — hardlinks, no second
    # download — and then pointed back at the real remote so a push goes where
    # the operator expects rather than into a peer's workspace.
    failed = 0
    for agent in rest:
        path = os.path.join(WORKDIR_ROOT, agent, repo)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        out = _git("clone", first_path, path)
        if out.returncode != 0:
            print(f"  {agent}: FAILED — {out.stderr.strip()}", file=sys.stderr)
            failed += 1
            continue
        fix = _git("-C", path, "remote", "set-url", "origin", args.url)
        if fix.returncode != 0:
            print(f"  {agent}: cloned, but origin still points at {first}'s copy",
                  file=sys.stderr)
            failed += 1
            continue
        print(f"  {agent}: cloned from {first}, origin -> {args.url}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
