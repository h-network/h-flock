# Build 05 — served API documentation

> Small. One lane, one deliverable: a page an app author can read without
> cloning this repo.
>
> **Base on `main`.** Branch `api/build-05-apidoc`, push to origin.

## 1. Why, given FastAPI already generates docs

`/docs` and `/redoc` exist and are useful, but they describe the *shape* of the
REST surface and cannot describe the two things an app author most needs:

- **What to put in an envelope.** `POST /agents/{agent}/envelopes` is documented
  as `type: object, additionalProperties: true` — which is correct, because the
  api must not know what kinds exist (`LLD-api` §3). So the generated schema
  says nothing about `kind` or `payload`.
- **The session protocol.** WebSocket routes cannot be expressed in OpenAPI, so
  `:8081/docs` is an empty page. The message shapes exist only in `LLD-session`.

## 2. Deliverable

**`GET /restdoc` on the api (:8080)** — a self-contained HTML page, no external
assets, no build step. Serving it from the api rather than a static file means it
ships with the thing it documents and cannot drift out of the image.

It covers, with a working `curl` for each:

**The REST surface** — every endpoint, what it returns, and the bearer token.
Pull the endpoint list from the app's own routes where you can, so the page
cannot silently fall behind a route that was added or removed.

**The kinds** — the four in `CONTRACTS` §6, with their payloads:

| `kind` | Payload | Does |
|---|---|---|
| `Message` | `{"text": …}` | `[message from <producer>] <text>` into the window |
| `Command` | `{"text": …}` | pasted bare — **it executes** |
| `StartAgent` | `{"agent": …, "cli": "claude"}` | enrol, window, CLI |
| `StopAgent` | `{"agent": …}` | reverses all three |

⚠ Say plainly on the page that **this list is current, not authoritative** — the
api does not validate `kind`, an unknown one returns `202` and then dead-letters
at the far edge with a reason. An app should not treat the list as a whitelist,
and the page will lag whenever an opener is added. That is the design working,
not a documentation bug.

**The session socket** — `ws://…:8081/session`, the bearer token, and the message
shapes both ways: `{"subscribe": [...], "mode": "read-only"|"read-write"}`,
`{"agent", "data"}` in and out, `{"error"}`. Note the fixed 120×32 and that no
client may resize (`LLD-tmux-host` §3).

**What a `202` means** — on the bus, not delivered. `LLD-api` §3. Worth stating
because it is the single most likely wrong assumption an app will make.

## 3. Also decide: should the generated docs need the token?

`/docs`, `/redoc` and `/openapi.json` currently answer **200 with no auth**,
while `LLD-api` §6 says the token is *"checked on every request including
reads"*. Now that the api is published on `0.0.0.0` that inconsistency is
reachable from the network. It leaks the surface, not data.

Pick one and make the code and §6 agree:

- **Require the token on all of them**, `/restdoc` included. Consistent with §6,
  and the app author gets the token before they need the page anyway.
- **Exempt the doc routes deliberately**, and say so in §6 — a documentation
  page is not a read of tenant state.

Either is defensible. Two things being true at once is not. Say which you chose
when you report.

## 4. Done when

- `curl http://<host>:8080/restdoc` returns a page that renders standalone
- every REST endpoint on it has a `curl` that works as written
- the four kinds and the session message shapes are on it
- `/docs` auth matches whatever §6 says after your change

## 5. Reporting

`jira done`, then message `architect` with the path, the endpoint, and which way
you resolved §3.
