# Build 36 — the two boundaries that are real

> ✅ **Shipped and demonstrated on the lab**, all three forced rather than
> reasoned about — see §4. `main` at 293 tests.

> Everything that crosses out of the container, and the one claim that crosses
> between agents. Small, and the last framework items before the list is
> decisions and parked work only.
>
> **Base on `main`.** Branch `<lane>/build-36-<piece>`, push to origin.

⚠ **Scope, so nobody builds the wrong thing.** h-flock is a **development
office** — agents are colleagues who were hired, not untrusted callers. Nothing
here isolates agents from each other. See `TODO`: that belongs to a different
product.

## 1. Port security on `producer` — `bus`

The router already computes the truth and throws it away:

```
  sender = source_key.split(":")[-2]      # derived from the queue it popped
  ...
  self.r.rpush(prefix(..., recipient, "ingress"), raw)    # forwards it unchanged
```

So `producer` is whatever the sender wrote, and nothing compares the two. It is a
switch reading the ingress port and not checking the source address against it.

⚠ **This is attribution, not defence.** The failure it fixes is *wrong
information*: a plumbing fixture made an operator's terminal display
`[message from telegram]` from a client that did not exist, and neither the
recipient nor the audit trail could contradict it.

**Stamp `producer` from the queue before forwarding.** Overwrite rather than
reject:

- nothing legitimate can mismatch — `send()` writes the header and picks the
  queue from one argument — so a mismatch means something wrote a queue directly
- ⚠ **do not dead-letter on mismatch.** Dropping lets anything that can write a
  queue destroy another agent's traffic; correcting keeps the office running and
  makes the claim honest
- log a lifecycle record when a stamp actually changes the value, so a forged
  claim is visible rather than silently tidied
- ⚠ **broadcast keeps working**: the sender is already excluded by the same
  derived value

Then say it plainly in `LLD-bus-and-router` and tell me the line for `HLD`
invariant 2, which I own and which currently describes the old behaviour.

## 2. TLS on both doors — `api`

`uvicorn.run` takes `ssl_certfile` and `ssl_keyfile`. Add them to the api and the
session door, from `API_TLS_CERT` / `API_TLS_KEY` and the session equivalents.

⚠ **Refuse to serve a non-loopback bind without TLS**, exactly as the api
already refuses one without a token:

```
  raise RuntimeError("API_TOKEN is required when API_BIND is not loopback")
```

A tenant published beyond loopback sends its bearer token in clear text today,
and the console makes exactly that easy. Exit with an explanation; do not warn
and continue — a warning in a log is how this ships by accident.

- certs arrive like credentials: `docker cp` from `container/home/`, never baked
  into the image, never a volume (`LLD-container` §3)
- ⚠ **say what a self-signed cert costs.** A browser will refuse the session
  WebSocket until the cert is trusted, and that failure looks like a broken
  terminal rather than a certificate problem. Put it in the README

## 3. Not doing: a Redis password

⚠ **Measured before specifying:** Redis binds `127.0.0.1` inside the container
(`entrypoint.sh`) and only 8080 and 8081 are published. Nothing outside the
container can reach it, so `requirepass` would guard a door that does not exist —
and it cannot be kept from an agent anyway, since `office` runs in the agent's
own window.

**Instead, guard the mistake that would open it:** if the Redis bind is ever
widened beyond loopback, the tenant must refuse to start without a password. One
check in `entrypoint.sh`, `tmux`'s file.

## 4. Done when — what actually happened

- **forged producer:** an envelope claiming `producer: telegram` written straight
  into `architect`'s egress arrived at the recipient as `producer: architect`,
  and the router logged it:
  `producer_stamped … "claimed producer 'telegram' stamped from egress sender 'architect'"`
- **both doors:** `API_BIND=0.0.0.0` with no cert →
  `RuntimeError: API_TLS_CERT and API_TLS_KEY are required when API_BIND is not loopback`,
  and the same for `SESSION_BIND`
- **widened Redis bind:** `REDIS_BIND=0.0.0.0` with no password →
  `entrypoint: REDIS_PASSWORD is required when REDIS_BIND is not loopback ('0.0.0.0')`
  and the tenant stopped, `exit=1`
- ⚠ **and the password path itself now works.** It was half-built: `redis-cli`
  prints `NOAUTH` and still exits 0, so readiness passed while every seeding
  command failed silently — a tenant that starts with an empty roster and no
  error. With the `rcli` helper, a passworded tenant seeds
  `architect,api,host` and an unauthenticated read gets `NOAUTH`.
- ⚠ **`producer_stamped` goes to stdout, not to a Redis list** — the log is the
  container's stdout (`docker logs`). Worth knowing before writing a checker
  that looks in Redis and concludes nothing was logged.

## 4b. Originally specified as

- a forged `producer` arrives stamped with the queue's own sender, and the
  correction is logged
- both doors serve TLS, and refuse a non-loopback bind without it
- a widened Redis bind without a password stops the tenant starting
- ⚠ **each demonstrated**: forge a producer by writing an egress directly, start
  a door bound to `0.0.0.0` with no cert, and widen the Redis bind. Paste what
  happened

## 5. Reporting

`jira done`, then message `architect` with the commit you worked from, what you
changed, and what you forced.
