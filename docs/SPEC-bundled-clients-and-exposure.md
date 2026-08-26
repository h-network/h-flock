# SPEC — bundled clients run in-tenant, and exposure becomes an explicit choice

Two changes, one theme: **the example clients should work without publishing
anything, and publishing should be a decision the operator makes knowingly.**

## The problem today

`setup.sh` asks *"Run the Telegram bot against this tenant?"*. Answering yes
enables the api door and prints a command. It never asks for a bot token or a
chat id, writes no Telegram config, and starts nothing. The bot is a **host**
process — `clients/` is not in the image and there is no compose service for it
— so it needs the api published to reach the tenant.

⚠ Worse, without `TELEGRAM_BOT_TOKEN` the bot runs in **dry-run mode**: it prints
formatted send operations to stdout and delivers nothing. An operator who runs
the printed command sees activity and gets no messages.

⚠⚠ And exposure is not currently a choice. `compose.yaml` publishes **both**
mappings unconditionally, with `API_HOST` defaulting to `0.0.0.0`:

    ports:
      - "${API_HOST:-0.0.0.0}:${API_PORT:-8080}:8080"
      - "${SESSION_HOST:-0.0.0.0}:${SESSION_PORT:-8081}:8081"

`API_ENABLED` governs whether the api **service runs**, not whether it is
**published**. Those are different questions and the prompt conflates them.

## 1. Bundled clients run inside the tenant

`clients/telegram` and `clients/web` are the shipped examples. Both should run in
the container by default, reaching the api on container-local `127.0.0.1:8080`.

- Copy `clients/` into the image.
- Start a bundled client from the entrypoint **only when it is configured** — the
  Telegram bot only when a token is present. A client that cannot work must not
  be started; a dry-run bot presented as running is the defect this fixes.
- Its config lives in `container/.env` with everything else. One config location,
  not two.

⚠ A bundled client that fails must not take the tenant down. Log the reason and
leave the tenant serving.

## 2. `setup.sh` asks for Telegram credentials

When the operator answers yes:

    TELEGRAM_BOT_TOKEN   required — without it there is nothing to run
    TELEGRAM_CHAT_ID     required — where messages go

Blank for either means the bot is **not** enabled, said plainly at the prompt
rather than discovered later. ⚠ The token is a credential: it goes to
`container/.env`, is never echoed back, and never appears in a summary line.

## 3. Exposure becomes an explicit, separate question

Split the two questions the api prompt currently merges:

    Start the REST API? [y/N]
      -> the service runs inside the tenant. Bundled clients need only this.

    Reach it from outside the container? [y/N]
      -> publishes a host port. Needed only for your own tools -- curl, a
         browser, a client you wrote. NOT needed by the bundled clients.

⚠ **Say what publishing means in the prompt**, not in a summary printed after the
answer. An operator deciding exposure needs to know at the moment of deciding
that `0.0.0.0` means every interface on the host.

**When nothing is published, publish nothing** — the compose mapping should be
absent, not merely bound to loopback. A mapping that exists is a mapping someone
can widen later without re-deciding.

The session console is browsed from a human's machine, so it will usually be
published; that is a legitimate yes rather than an exception to the rule.

## Out of scope

- Changing the existing TLS / `ALLOW_PLAINTEXT_PUBLISH` guard, which already
  refuses to start a plaintext door published beyond loopback
- Any change to `API_ENABLED`'s meaning as the service switch
- Bundling clients that are not the shipped examples
