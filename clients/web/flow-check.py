#!/usr/bin/env python3
"""flow-check — drive the console like an operator and report what happened.

    python3 clients/web/flow-check.py --console http://HOST:8098 --secret S \
        --container h-flock-<tenant>-tenant-1 --ssh <user@host> --tenant <name>

⚠ **Every flow here is a bug an operator hit in use.** The console had tests
before this file existed — they asserted that files exist and that no token
leaks into browser assets, and they passed while the terminals view ignored a
hire and the chat lost everything on refresh. Static checks cannot see a
running page, so the rule this file exists to enforce is:

    a reported bug becomes a failing flow here FIRST, then a fix.

That is why a red result is normal on the day a defect is reported, and why
this exits non-zero: it is a gate, not a report card.

⚠ **What it cannot tell you.** It proves a flow completed and that state
reached the screen. It says nothing about whether the result looks right —
`visual-check.py` makes the same disclaimer and it is just as true here. Taste,
jank and "feels wrong" still need a person.

⚠ **It needs a real tenant.** Docker and a browser, which no lane has today.
Run it where both exist.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

FLOWS: list[str] = []


def run_remote(ssh: str, command: str, timeout: int = 120) -> str:
    """Run a command next to the tenant. Local when --ssh is omitted."""
    argv = (["ssh", ssh, command] if ssh else ["bash", "-lc", command])
    done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return done.stdout.strip()


class Console:
    """The operator's browser."""

    def __init__(self, page, base: str):
        self.page, self.base = page, base

    def login(self, secret: str) -> None:
        self.page.goto(self.base + "/", wait_until="networkidle", timeout=30000)
        field = self.page.query_selector("input[type=password], input[name=secret], input#secret")
        if field:
            field.fill(secret)
            button = self.page.query_selector("button[type=submit], form button")
            button.click() if button else self.page.keyboard.press("Enter")
            self.page.wait_for_timeout(3000)

    def go(self, fragment: str, settle: int = 5000) -> None:
        self.page.goto(f"{self.base}/#{fragment}", wait_until="networkidle", timeout=30000)
        self.page.wait_for_timeout(settle)

    def tabs(self) -> list[str]:
        return self.page.evaluate("() => [...document.querySelectorAll('.term-tab')].map(e => e.dataset.agent)")

    def conversation(self) -> str:
        return self.page.evaluate(
            "() => [...document.querySelectorAll('.conversation-message')].map(e => e.textContent).join(' | ')"
        )


def flow(name: str):
    def decorate(fn):
        FLOWS.append((name, fn))
        return fn
    return decorate


@flow("a hire reaches the terminals view without a reload")
def hire_appears(console: Console, ctx) -> tuple[bool, str]:
    console.go("/terminals")
    before = console.tabs()
    ctx["envelope"]("StartAgent", ctx["probe"], cli="claude")
    for _ in range(20):
        console.page.wait_for_timeout(2000)
        if ctx["probe"] in console.tabs():
            return True, f"{before} -> {console.tabs()}"
    return False, f"{before} -> {console.tabs()} (never appeared)"


@flow("a tab the operator closed stays closed")
def closed_stays_closed(console: Console, ctx) -> tuple[bool, str]:
    tabs = console.tabs()
    if ctx["probe"] not in tabs:
        return False, "probe tab missing; the hire flow must pass first"
    console.page.click(f'.term-tab-close[data-close="{ctx["probe"]}"]')
    console.page.wait_for_timeout(12000)  # several roster polls
    return ctx["probe"] not in console.tabs(), f"after close + 12s: {console.tabs()}"


@flow("a retired agent's tab disappears")
def retired_tab_goes(console: Console, ctx) -> tuple[bool, str]:
    second = ctx["probe"] + "-b"
    ctx["envelope"]("StartAgent", second, cli="claude")
    for _ in range(20):
        console.page.wait_for_timeout(2000)
        if second in console.tabs():
            break
    else:
        return False, "the second probe never got a tab"
    ctx["envelope"]("StopAgent", second)
    for _ in range(20):
        console.page.wait_for_timeout(2000)
        if second not in console.tabs():
            return True, f"tab removed on retire: {console.tabs()}"
    return False, f"tab survived the retire: {console.tabs()}"


@flow("what the operator typed survives a refresh")
def chat_survives_refresh(console: Console, ctx) -> tuple[bool, str]:
    marker = f"flow-check-{ctx['stamp']}"
    console.go(f"/agents/{ctx['agent']}")
    # ⚠ #message inside form#composer, and Ctrl+Enter sends — plain Enter is a
    # newline. Written against a guessed selector first, this flow failed with
    # "never rendered", which reads like the product losing the message when in
    # fact nothing was ever sent. A check that fails for the wrong reason is
    # worse than no check.
    box = console.page.query_selector("#message")
    if not box or box.is_disabled():
        return False, "composer #message missing or disabled — is an agent selected?"
    box.fill(marker)
    console.page.keyboard.press("Control+Enter")
    console.page.wait_for_timeout(4000)
    if marker not in console.conversation():
        return False, "the message never rendered at all"
    console.page.reload(wait_until="networkidle", timeout=30000)
    console.page.wait_for_timeout(6000)
    survived = marker in console.conversation()
    return survived, ("still there after reload" if survived
                      else "gone after reload — outbound history has no durable source")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--console", required=True, help="base url of the console server")
    ap.add_argument("--secret", required=True)
    ap.add_argument("--container", required=True, help="tenant container name")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--ssh", default="", help="user@host the tenant runs on; blank for local")
    ap.add_argument("--agent", default="", help="an existing agent to converse with")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed — see the module docstring", file=sys.stderr)
        return 2

    stamp = str(subprocess.run(["date", "+%H%M%S"], capture_output=True, text=True).stdout.strip())

    def envelope(kind: str, agent: str, **payload) -> None:
        body = json.dumps({"kind": kind, "payload": {"agent": agent, **payload}})
        run_remote(args.ssh,
                   f"docker exec {args.container} sh -lc "
                   f"'curl -s -o /dev/null -H \"Authorization: Bearer $API_TOKEN\" "
                   f"-X POST -H \"Content-Type: application/json\" -d {json.dumps(body)} "
                   f"http://127.0.0.1:8080/agents/host/envelopes'")

    agent = args.agent or run_remote(
        args.ssh,
        f"docker exec {args.container} redis-cli --no-raw HGETALL "
        f"pod:acme:tenant:{args.tenant}:roster | paste - - | grep '\"tmux\"' "
        f"| awk -F'\"' '{{print $2}}' | head -1")
    ctx = {"envelope": envelope, "probe": f"flowprobe{stamp}", "stamp": stamp, "agent": agent}

    print(f"console={args.console}  tenant={args.tenant}  agent={agent}\n")
    failures = 0
    with sync_playwright() as play:
        browser = play.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
        console = Console(page, args.console)
        console.login(args.secret)

        for name, fn in FLOWS:
            try:
                ok, detail = fn(console, ctx)
            except Exception as exc:                      # a flow that throws is a failing flow
                ok, detail = False, f"raised {type(exc).__name__}: {exc}"
            failures += not ok
            print(f"{'ok  ' if ok else 'FAIL'} {name}\n       {detail}")

        # ⚠ Tidy up after ourselves. A checker that leaves fixtures in someone's
        # office is how `[message from telegram]` ended up in an operator's
        # terminal — twice.
        for name in (ctx["probe"], ctx["probe"] + "-b"):
            envelope("StopAgent", name)
        if errors:
            print("\nconsole errors raised by the page:")
            for line in errors[:5]:
                print("   ", line)
        browser.close()

    print(f"\n{'FAILING FLOWS: ' + str(failures) if failures else 'all flows green'}")
    print("⚠ Flows prove state reached the screen. They do not prove it looks right.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
