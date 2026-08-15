# Build 73 — v4: reserved header space, TTL and hop count

> **Base on `main`.** Branch `bus/build-73-v4-reserved`, push to origin.
> Owner: `bus` (`flock/bus/envelope.py`, `flock/switch/service.py`).

## 1. Why this build exists — read this before the layout

⚠ **The primary deliverable is the RESERVED SPACE, not the TTL.**

Today every new L2 field moves `HEADER_WIDTH`, which moves where the body starts,
which makes every in-flight frame unreadable — so each field costs a version
bump, a coordinated deploy and a `purge_transport`. Reserved bytes at the end of
the header mean `HEADER_WIDTH` **never moves again**: a new field consumes
reserved space, the body stays put, and an older reader parses the fields it
knows and ignores the rest.

**This is the last cheap moment to do it.** Reserving costs a wire break either
way, so it is spent once, together with the two fields we already know we want.

⚠ **Format forward-compatibility is not semantic forward-compatibility.** A v4
reader given a frame using a field it does not know will *parse* it fine and
*ignore* the meaning. A field that changes behaviour may still warrant a version
bump — that becomes a policy choice rather than a format necessity, which is the
whole point.

## 2. ⚠ TTL does NOT close the bug it is queued against. Say so, do not oversell it

`TODO.md:33` records the demonstrated fault: **four agents replied to each other
for three hours and 1,252 envelopes**, stopped only because a human typed a line.
It proposes "an envelope field, a decrement at forward and a dead-letter at zero
is the whole mechanism".

⚠ **That mechanism does not stop that fault, and I verified why:**

- `port/openers.py:73` pastes **`[message from {source}] {text}`** into the pane.
  The agent never sees `stream_id`, `correlation_id`, or any depth.
- `office/cli.py:86 _message` calls `send()` with **no `correlation_id`**, so
  `build()` mints a fresh one.

**So a reply is a brand-new envelope with fresh lineage.** It would start at full
TTL. That loop runs identically with this build merged.

**What TTL genuinely buys** is a forwarding-loop bound — the same frame
circulating — which needs the router (unbuilt) to be reachable at all, plus a
cheap bound on any future L3 path. It is the correct L2 primitive and it is
nearly free. ⚠ **It is groundwork, not a fix.**

**What would actually close `TODO.md:33`** is one of: propagating a conversation
depth through the reply (needs a reply path that carries lineage — **none exists
today**), or a rate limit per `(source, destination)`, or a rate limit on
`destination: all`. ⚠ **All three are out of scope here. Do not attempt them.**

## 3. The v4 header — 256 bytes

| offset | width | field | contents |
|---:|---:|---|---|
| 0 | 1 | `v` | `4` |
| 1 | 32 | `stream_id` | `uuid4().hex` |
| 33 | 32 | `correlation_id` | `uuid4().hex` |
| 65 | 63 | L2 `source` | agent name, space-padded |
| 128 | 63 | L2 `destination` | agent name or `all`, space-padded |
| **191** | **3** | **`ttl`** | ASCII digits, default **`016`** |
| **194** | **3** | **`hops`** | ASCII digits, starts **`000`** |
| **197** | **59** | **RESERVED** | **spaces** |
| 256 | — | body | JSON: `kind`, `ts`, `l3`, `payload` |

⚠ **TTL default is 16, not 64.** The longest conceivable path here is
agent → switch → router → switch → agent. 64 is cargo-culted from IP; 16 is 5×
headroom over anything we can build.

### The rules that make reservation work — all three are load-bearing

1. ⚠ **Reserved bytes are SPACES.** Not nulls — `redis-cli LRANGE` stays
   readable, same reason as v3.
2. ⚠ **An allocated field that is all spaces means ABSENT.** That is what lets a
   newer reader accept a frame from an older sender.
3. ⚠ **`HEADER_WIDTH` is now frozen at 256.** A future field takes reserved
   space. **If you ever need to move it, that is a new version — and this build
   failed.**

## 4. Switch behaviour

At forward, on the **header only**:

- **decrement `ttl`**; **increment `hops`**
- **`ttl` reaching 0 → dead-letter**, `reason` naming ttl expiry, **no kick**
- both are **splices**, exactly like `stamp_source` — ⚠ **the body must not be
  read, decoded or re-encoded**

⚠ **This is where build 72 is most likely to be undone.** Two new numeric fields
invite `json.loads` for convenience. It must stay at zero.

## 5. Done when

- ⚠ **`rg 'json\.' src/flock/switch/service.py` is EMPTY** — build 72's invariant
  is a regression gate here, not an aspiration
- switch read cost still **flat** 16 B → 1 MiB, both payload shapes, ~3 µs
  (`container/scenarios/frame-cost-sweep.py`, h-oracle)
- body **byte-identical** sender → port across ttl decrement, hop increment and a
  source stamp **together**
- ⚠ **negative controls** per `BUILD-CONVENTION` §1:
  - a frame injected with `ttl=001` dead-letters at the next forward, with the
    reason, and **is not kicked**
  - a frame whose reserved bytes are non-space **still parses**, proving rule 2
  - `hops` increments across a real delivery
- `python3 -m pytest -q` green (386 at the time of writing)
- `container/accept.sh` green; conservation unchanged: **zero duplicates**
- frame grows 351 → **416 bytes** at a small payload — state it, do not bury it
- ⚠ `purge_transport` still clears transport queues at boot for the v3 → v4 break
  — **verify, do not assume** (`DESIGN-layers:442`, build 63)

## 6. Reporting

`jira done`, then message `architect` with the flat-read table, confirmation that
`json.` is still absent from the switch, the three negative controls, the frame
size delta, and ⚠ **an explicit statement that this build does NOT close
`TODO.md:33`** — so the next person reading the changelog is not misled by a
field named `ttl`.

Then add a `CHANGELOG.md` entry naming what v4 made false.
