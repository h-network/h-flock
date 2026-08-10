#!/usr/bin/env python3
"""visual-check — render the console in a real browser and report what it does.

    python3 clients/web/visual-check.py [--url http://127.0.0.1:8085] [--out ./shots]

⚠ Until this existed, every visual claim in this build was reasoning. A headless
Chromium is installed on the architect host:

    sudo pip install --break-system-packages playwright
    python3 -m playwright install --with-deps chromium

What it reports, none of which can be judged by reading source:

  - console errors and warnings the page raises
  - requests that failed (a module that 404s is invisible in a diff)
  - horizontal overflow at each viewport, which is what "responsive" means here
  - layout shift while data arrives, the thing SPEC calls out and nobody could measure
  - element counts, so "it rendered" is a number rather than an opinion
  - screenshots in light and dark, because prefers-color-scheme has two answers

⚠ A screenshot is evidence that something rendered. It is not evidence that it
looks right — a person still has to look. Say which you have.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

VIEWPORTS = [("1600x900", 1600, 900), ("1280x720", 1280, 720), ("1024x768", 1024, 768)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8085")
    ap.add_argument("--out", default="shots")  # gitignored; screenshots are evidence, not source
    ap.add_argument("--settle", type=int, default=2500, help="ms to wait after networkidle")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed — see the module docstring", file=sys.stderr)
        return 2

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    failures = 0

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for scheme in ("light", "dark"):
            for label, width, height in VIEWPORTS:
                errors: list[str] = []
                failed: list[str] = []
                page = browser.new_page(viewport={"width": width, "height": height}, color_scheme=scheme)
                page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
                page.on("requestfailed", lambda r: failed.append(f"{r.url} :: {r.failure}"))

                # Cumulative layout shift, observed while the panels fill in.
                page.add_init_script(
                    "window.__cls = 0;"
                    "new PerformanceObserver(l => { for (const e of l.getEntries())"
                    " if (!e.hadRecentInput) window.__cls += e.value; })"
                    ".observe({type: 'layout-shift', buffered: true});"
                )
                page.goto(args.url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(args.settle)

                shot = out / f"{scheme}-{label}.png"
                page.screenshot(path=str(shot))
                metrics = page.evaluate(
                    "() => ({"
                    " overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,"
                    " scrollW: document.documentElement.scrollWidth,"
                    " clientW: document.documentElement.clientWidth,"
                    " cls: window.__cls || 0,"
                    " panels: [...document.querySelectorAll(\"[id$='-panel']\")].map(e => e.id),"
                    " focusable: document.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex=\\'-1\\'])').length,"
                    " aria: document.querySelectorAll('[aria-label], [aria-live], [role]').length"
                    "})"
                )
                bad = bool(errors or failed or metrics["overflow"] or metrics["cls"] > 0.1)
                failures += bad
                print(f"{'FAIL' if bad else 'ok  '} {scheme:5} {label:9} "
                      f"overflow={metrics['overflow']} cls={metrics['cls']:.3f} "
                      f"panels={len(metrics['panels'])} focusable={metrics['focusable']} aria={metrics['aria']} -> {shot.name}")
                if errors:
                    print("      console:", json.dumps(errors[:5]))
                if failed:
                    print("      failed requests:", json.dumps(failed[:5]))
                page.close()
        browser.close()

    print(f"\n{'FAILURES: ' + str(failures) if failures else 'all viewports clean'}")
    print("⚠ Screenshots prove it rendered. They do not prove it looks right.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
