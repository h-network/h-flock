# Verification Report — api Lane (2026-08-22)

Verification of the `api` lane's living documentation against the codebase as of `main` at `c405bf6`.

Lane files audited:
- `docs/LLD-api.md`
- `docs/LLD-session.md`
- `docs/API.md`
- `docs/INVARIANTS-api.md`
- `docs/NAMING-api.md`

---

## 1. Contradictions

1. **Wire frame schema version in `LLD-api.md` (§3):**
   - *Doc stated:* `LLD-api.md:68` stated "Build a `v=2` layered wire frame with the `destination` from the path...".
   - *Code does:* `src/flock/bus/envelope.py:34-40` and `src/flock/api/app.py:650-655` construct version 4 layered wire frames (`v: 4`, `ttl: 16`, `hops: 0`).
   - *Action taken:* Corrected `LLD-api.md` to `v=4`.

2. **Duplicate fields in `API.md` (§3 example response):**
   - *Doc stated:* `API.md:178-180` in the Quick Start mailbox retrieval example had duplicate inline keys:
     ```json
       "ttl": 16,
       "hops": 0,
       "ttl": 16, "hops": 0, "l3": {"source": "acme:hq:backend", "destination": "acme:hq:telegram"},
     ```
   - *Code does:* `src/flock/bus/envelope.py:40-52` emits single `ttl`, `hops`, and `l3` dictionary fields.
   - *Action taken:* Removed the duplicate `"ttl": 16, "hops": 0,` line from `API.md`.

3. **Stale v3 error table reference in `API.md` (§7):**
   - *Doc stated:* `API.md:808` stated "Request envelope structure does not conform to the v3 frame specification."
   - *Code does:* Platform enforces the `v=4` wire frame schema (`src/flock/bus/envelope.py:58`).
   - *Action taken:* Updated `API.md:808` to refer to the `v4` frame specification.

---

## 2. Absences & Architectural Determinations

1. **`office usage` & Aggregated Usage Stream:**
   - *Observation:* Build 82 introduced `office usage [--agent <name>] [--since <ISO>] [--json]` in `src/flock/office/cli.py:590-660`, which reads token usage and USD pricing data from Redis stream `pod:<pod>:tenant:<tenant>:usage` via the RESP client (`flock.bus.resp.Redis.xrange`).
   - *Determination for `API.md`:* `office usage` is **not** an HTTP REST endpoint on `flock.api` (`:8080`). `API.md` is strictly the reference for external HTTP/WebSocket clients. Adding CLI operator commands to `API.md` would confuse external developers with local operator tooling.
   - *Action taken:*
     - Added an explicit clarification in `docs/LLD-api.md` §8 ("What this is not") stating that usage reporting (`office usage`) is an operator CLI query over Redis stream `pod:<pod>:tenant:<tenant>:usage`, not an HTTP endpoint on `flock.api`.
     - Documented `pod:<p>:tenant:<t>:usage` in `docs/NAMING-api.md` (Table 1) with tier C classification.

2. **Synchronous RESP Client Stream Extensions (`flock.bus.resp.Redis`):**
   - *Observation:* `src/flock/bus/resp.py` gained `xrange`, `xrevrange`, `xdel`, and `xlen`.
   - *Determination:* `resp.py` is the minimal client used by the `office` CLI and entrypoint scripts. Documenting its stream reading methods in `NAMING-bus.md` / `CONTRACTS.md` is recommended for the bus lane.

3. **Shipped Pricing Configuration (`container/config/pricing.json`):**
   - *Observation:* Container config file containing canonical model token pricing rates is baked into `/app/container/config/pricing.json` and `/etc/flock/pricing.json`.
   - *Determination:* Operator/container configuration; documented in `BUILD-82-results.md` and belongs in `LLD-container.md` (architect lane).

---

## 3. Stale Citations & Near Misses

- Ran `python3 tools/check_citations.py` unpiped across the entire repository.
- **Results for `api` lane docs (`LLD-api.md`, `LLD-session.md`, `API.md`, `INVARIANTS-api.md`, `NAMING-api.md`):**
  - **0 hard failures.**
  - **0 near misses.**
- Audited line numbers in `docs/NAMING-api.md` against current definitions in `src/flock/session/app.py` and updated line references for `SessionSettings`, `_authorized`, `_connection_log`, `create_app`, `SESSION_BIND`, `SESSION_PORT`, `TMUX_SESSION`, `TMUX_SOCKET`, and `SESSION_TLS_CERT`.
- Fixed typo in `docs/NAMING-api.md:54`: `pod:<p>:tenant:<t>:agent:<a>:tasks.<s` corrected to `pod:<p>:tenant:<t>:agent:<a>:tasks.<state>`.

---

## 4. Summary of Changes in Lane

- `docs/LLD-api.md`: Updated wire frame version to `v=4` (§3) and added usage distinction in §8.
- `docs/API.md`: Fixed duplicate JSON fields in Quick Start (§3) and updated v3 -> v4 reference in §7.
- `docs/NAMING-api.md`: Updated `src/flock/session/app.py` citation lines, fixed `tasks.<state>` key name, and added `usage` stream key.
- `docs/VERIFY-2026-08-22-api.md`: Created verification report for the lane.

---

## 5. Items for Architect

- **Living doc home for `office usage`:** Since `office usage` is an operator CLI command querying Redis directly, it should be documented in `CONTRACTS.md` or `LLD-container.md` rather than `API.md`.
- **`FLOCK_CUSTODY_FILE` and `delivery.markers`:** Both belong to the `bus` and `tmux` lanes (`CONTRACTS.md` §3/§4 and `LLD-port-tmux.md`), and are absent from `api` door surfaces as expected.
