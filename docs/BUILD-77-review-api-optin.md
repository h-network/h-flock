# Build 77 — review the opt-in api door and the setup prompts

> **Base on `main`** at `40a8ede`. ⚠ **REVIEW ONLY — no code, no fixes.**
> Report findings; I land any change. Owner: `api` (you wrote
> `clients/telegram/bot.py` and own `flock/api`).

## What changed, and why you

Three commits, all mine, none reviewed by anyone:

- `474fe45` — `API_ENABLED` defaults to **0**; the api door does not start
- `40a8ede` — `setup.sh` asks which doors and which host ports
- plus the healthcheck: with the door off, liveness is the switch + Redis

⚠ **I am spec author, implementer and sole reviewer of all three.** That is the
weakest possible arrangement and it is why this ticket exists.

## What I want attacked, in order

1. ⚠ **INDUCE A FAILURE, do not reason about one.** Build the case where this
   breaks. Two tenants on one host. A `.env` written before the default changed.
   `API_ENABLED=1` with the port already held. Telegram answered yes, API no.
   **A constructed failing case beats a careful read** — see if the prompts can
   produce a `.env` that yields an unhealthy tenant.
2. **The free-port probe.** `setup.sh` binds a socket to test. My first version
   piped `ss` to `grep` and silently passed everywhere `ss` is absent. **Ask
   what would make the replacement silently pass too** — no probe binary, a
   port held on `127.0.0.1` only, IPv6, a port in `TIME_WAIT`, macOS.
3. **The Telegram dependency.** I assert `bot.py` cannot work without the api
   door because it takes `--api-url`. **You wrote it — is that actually true?**
   Any other path to the fabric makes the forced enable wrong.
4. **What I broke and have not fixed.** `accept.sh`, `plumbing-check.sh` and
   every scenario enrol over HTTP. With the new default they fail against a
   fresh tenant. I have **not** touched them. Is the right answer that they set
   `API_ENABLED=1`, or that the default is wrong?
5. **The healthcheck when the door is off.** `pgrep flock.switch` + `redis-cli
   ping`. A wedged switch still has a PID. **Is that a check that can fail?**

## Rules

- ⚠ **Name the SHA you read at.** `main` moves.
- ⚠ **Say what your green excluded.** I ran `pytest` and `check_citations`; I did
  **not** run `accept.sh`, and no tenant was built from the new `setup.sh` —
  there is no docker in my window.
- **Disagree in public.** I have been wrong repeatedly today; every correction
  came from a lane saying so.

## Done when

`jira done`, then message `architect` with: each induced failure and its exact
reproduction, your verdict on 3 and 4, and anything you could not make fail.
