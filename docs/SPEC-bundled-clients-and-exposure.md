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

## 1. The Telegram bot runs inside the tenant

`clients/telegram` is the shipped example of an **unattended** client — nobody
is at a keyboard driving it, so it belongs in the container, reaching the api
on container-local `127.0.0.1:8080`.

- Copy `clients/` into the image (this also carries `clients/web`; see below).
- Start the bot from the entrypoint **only when it is configured** — only when
  a token is present. A client that cannot work must not be started; a dry-run
  bot presented as running is the defect this fixes.
- Its config lives in `tenants/<tenant>/.env` with everything else. One config location,
  not two.

⚠ A bundled client that fails must not take the tenant down. Log the reason and
leave the tenant serving.

### `clients/web` is provisioned as a separate, optional container

`clients/web` is the shipped browser console, and it is not started from the
tenant entrypoint. It is not the same kind of client as the Telegram bot: it is
an **operator** service and runs in its own container only when setup explicitly
enables the Mini App.

`clients/web/server.py` is itself a security boundary, not a static file
server — shared operator secret, `HttpOnly`/`SameSite` session cookies, TLS
termination, an audit log, rate-limited login (`clients/web/README.md`,
`clients/web/SPEC.md` §6b). Setup generates and preserves its operator secret,
asks for the public HTTPS URL and host binding, and leaves TLS termination to
the operator's reverse proxy.

The tenant image still carries `clients/web` because `container/Dockerfile`
copies `clients/` wholesale, but provisioning builds the smaller, separate
`container/web.Dockerfile`. The generated service joins the tenant's private
Compose network, reaches the two doors by service DNS, and publishes only its
own fixed container port 8090 on the operator-selected host address and port.

## 2. `setup.sh` asks for Telegram credentials

When the operator answers yes:

    TELEGRAM_BOT_TOKEN   required — without it there is nothing to run
    TELEGRAM_CHAT_ID     required — where messages go

Blank for either means the bot is **not** enabled, said plainly at the prompt
rather than discovered later. ⚠ The token is a credential: it goes to
`tenants/<tenant>/.env`, is never echoed back, and never appears in a summary line.

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
