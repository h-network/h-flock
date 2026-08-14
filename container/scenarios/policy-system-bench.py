#!/usr/bin/env python3
"""Measure production tag policy at the port against switch-side alternatives."""

import json
import os
import statistics
import sys
import time

import redis

sys.path.insert(0, "/app/src")
from flock.bus import allows, prefix, tags_key

URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
POD = os.environ.get("POD", "acme")
TENANT = os.environ.get("TENANT", "bus-lab")
ITERATIONS = int(os.environ.get("ITERATIONS", "600"))
ROSTERS = (10, 100, 1000)
TAG_SIZES = (1, 5, 20)


def median_us(fn):
    samples = []
    fn()
    for _ in range(ITERATIONS):
        started = time.perf_counter_ns()
        fn()
        samples.append(time.perf_counter_ns() - started)
    return statistics.median(samples) / 1000


def main():
    r = redis.Redis.from_url(URL)
    roster = prefix(POD, TENANT, resource="roster")
    rows = []
    print(f"redis={URL} iterations={ITERATIONS}")
    print(
        "roster tags port_allow_us port_deny_us switch_memory_us "
        "forward_only_us forward_plus_memory_us port_allow_per_s "
        "port_deny_per_s switch_memory_per_s"
    )
    for size in ROSTERS:
        agents = [f"policy-{i}" for i in range(size)]
        r.hset(roster, mapping={agent: "api" for agent in agents})
        source, destination = agents[0], agents[-1]
        for tag_size in TAG_SIZES:
            shared = [f"tag-{i}" for i in range(tag_size)]
            r.hset(
                tags_key(POD, TENANT, source),
                mapping={"export": json.dumps(shared, separators=(",", ":"))},
            )
            r.hset(
                tags_key(POD, TENANT, destination),
                mapping={"import": json.dumps(shared, separators=(",", ":"))},
            )
            cached_export = set(shared)
            cached_import = set(shared)
            port_allow = median_us(
                lambda: allows(
                    r,
                    pod=POD,
                    tenant=TENANT,
                    source=source,
                    destination=destination,
                )
            )
            switch_memory = median_us(lambda: bool(cached_export & cached_import))
            forward_only = median_us(lambda: r.hexists(roster, destination))
            forward_plus = median_us(
                lambda: (r.hexists(roster, destination), bool(cached_export & cached_import))
            )

            denied_import = [f"denied-{i}" for i in range(tag_size)]
            r.hset(
                tags_key(POD, TENANT, destination),
                "import",
                json.dumps(denied_import, separators=(",", ":")),
            )
            port_deny = median_us(
                lambda: allows(
                    r,
                    pod=POD,
                    tenant=TENANT,
                    source=source,
                    destination=destination,
                )
            )
            row = (
                size,
                tag_size,
                port_allow,
                port_deny,
                switch_memory,
                forward_only,
                forward_plus,
            )
            rows.append(row)
            print(
                f"{size} {tag_size} {port_allow:.2f} {port_deny:.2f} "
                f"{switch_memory:.3f} {forward_only:.2f} {forward_plus:.2f} "
                f"{1e6/port_allow:.0f} {1e6/port_deny:.0f} {1e6/switch_memory:.0f}"
            )
            r.delete(tags_key(POD, TENANT, source), tags_key(POD, TENANT, destination))
        r.hdel(roster, *agents)

    # Dependency-free SVG: achievable decisions/s at the representative five-tag
    # policy. Lines against roster size make curve shape visible rather than
    # inviting a conclusion from one table cell.
    selected = [row for row in rows if row[1] == 5]
    series = {
        "port allow": [1e6 / row[2] for row in selected],
        "port deny": [1e6 / row[3] for row in selected],
        "switch memory": [1e6 / row[4] for row in selected],
    }
    width, height, margin = 760, 420, 55
    maximum = max(max(values) for values in series.values())
    colors = {"port allow": "#2878b5", "port deny": "#d9534f", "switch memory": "#2ca02c"}
    xs = [margin + i * (width - 2 * margin) / 2 for i in range(3)]
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}" stroke="black"/>',
        f'<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height-margin}" stroke="black"/>',
        '<text x="380" y="25" text-anchor="middle">Policy decisions/s vs roster size (5 tags)</text>',
    ]
    for x, size in zip(xs, ROSTERS):
        svg.append(f'<text x="{x}" y="390" text-anchor="middle">{size}</text>')
    for index, (name, values) in enumerate(series.items()):
        points = []
        for x, value in zip(xs, values):
            y = height - margin - value / maximum * (height - 2 * margin)
            points.append(f"{x:.1f},{y:.1f}")
        svg.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{colors[name]}" stroke-width="3"/>')
        svg.append(f'<text x="{width-210}" y="{50+index*20}" fill="{colors[name]}">{name}</text>')
    svg.append('</svg>')
    with open("/tmp/policy-system-bench.svg", "w", encoding="utf-8") as handle:
        handle.write("\n".join(svg))


if __name__ == "__main__":
    main()
