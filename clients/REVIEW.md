# Two clients — for review

Both built from [`docs/API.md`](../docs/API.md) and a token, and both exercised
against the lab tenant. Rollback point: **`verified-2026-08-09j`**.

## Try them

```bash
ssh h-lab@172.16.0.14
cd ~/h-flock-work/h-flock
T=$(docker exec h-flock-hq-tenant-1 printenv API_TOKEN)

# web — then open http://127.0.0.1:8090 (tunnel it, or curl the proxy)
API_TOKEN="$T" python3 clients/web/server.py --api http://127.0.0.1:8080

# telegram, no bot token needed — real tenant, printed Telegram calls
python3 clients/telegram/bot.py --api-url http://127.0.0.1:8080 \
        --api-token "$T" --agent demo --prompt "run ls then reply DONE"
```

## What they do

**Telegram** — one chat, one agent. The shape is h-cli's: **one message, edited
in place** as tool calls arrive, then the answer as its own message.

```
⏳ demo is working
   1. ⚙ Bash
   2. ⚙ Bash

demo: TELEGRAM-OK
```

Typing refreshes on a timer while presence is `working` — Telegram's indicator
expires after ~5s, so it has to be re-sent, which is why presence is polled
rather than pushed. A `blocked` agent is reported as *not accepting messages*
rather than shown as typing forever.

**Web** — a standard-library server plus one page, no build step. The server
exists for two reasons that are not optional: h-flock sends **no CORS headers**,
and browser `EventSource` **cannot attach a Bearer token**. Proxying from one
origin solves both, and keeps the token server-side instead of shipping it to
every browser.

## The point of the exercise

`API.md` claimed a stranger could build against h-flock. Nobody had tried.

**Eight gaps, all now fixed** — `blocked` missing from the presence description,
enrolment idempotency unstated, SSE resume precedence between `?after=` and
`Last-Event-ID`, the activity vocabulary never enumerated, board entries possibly
bare strings, and the CORS/`EventSource` pair that forces every browser client to
ship a proxy.

⚠ **The lane that wrote `API.md` still hit five of them.** An author cannot see
what they assumed.

## Two bugs the clients found

**The bot's first live run died on its first call** — `enrol()` defined without
`self` while using it. Unit tests all passed; nothing had enrolled against a real
tenant.

**A live watchdog false alarm.** Exercising the tenant produced a real alert
saying agy's credential was *"expiring"* — about a timestamp already in the past,
for an account working fine. `token.expiry` is agy's **access** token, which the
CLI refreshes itself; measured across two machines hours apart, the value had
moved. agy is `unknown` now, like codex — two of three CLIs cannot be checked.

## One decision taken while you were out

**`clients/common/` was specced and then cancelled.** Both clients shipped their
own thin client inline, and extracting a shared one would serve two consumers of
genuinely different shapes — a same-origin proxy and a long-poll bot — over a few
dozen lines of overlap. Rule of three: two is not enough to know what the
abstraction should be, and a wrong shared library is harder to remove than
duplication is to live with.

## Not done

- **No Telegram bot token**, so the bot has never spoken to Telegram. Everything
  h-flock-side is exercised; the Telegram half is printed rather than sent.
- **The web page has been proven through its proxy, not through a browser.** Every
  call it makes returns correctly; nobody has looked at it rendered.
- Both are in `clients/` because there is no shared remote for them yet. They are
  consumers and belong in their own repository.
