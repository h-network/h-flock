# Build 77 — review of the opt-in API door and setup prompts

> **Base on `main`.** Branch `api/build-77-review-api-optin`, push to origin.
> Owner: `api`. ⚠ **REVIEW ONLY — no product code, no renames, no refactors.**
> Deliverable is one document.

## 1. Scope and target commits

This review evaluates three commits authored, implemented, and self-reviewed by `architect`:

1. `a4c32a5` — **The api door is opt-in** (`container/entrypoint.sh:66`, `container/entrypoint.sh:313`, `container/compose.yaml:66`, `container/compose.yaml:94`, `tests/test_entrypoint_publish.py:60-75`)
2. `474fe45` — **Document the api door's knobs in .env.example** (`container/.env.example:7`)
3. `94144f5` — **Move activity, presence and verification to the watchdog** (`src/flock/watchdog/service.py:366-407`, `src/flock/switch/service.py`, `tests/test_verification.py:155-206`)

---

## 2. Section 1: Inducing failure from the setup prompts (unhealthy / broken tenant)

### The Primary Failure: The False-Healthy API-Dead Tenant

Rather than a theoretical issue, this is a concrete failure reproducible on any fresh deployment:

```bash
# 1. Run host installer taking all defaults
./setup.sh
# Prompts: Pod [acme], Tenant [hq], Agents [3], Remote [Y], TLS cert [blank], Self-signed [y]

# 2. Installer completes successfully and reports:
# "Tenant 'hq' is healthy."
# "  api      https://127.0.0.1:8080   token in container/.env"
# "  session  wss://127.0.0.1:8081/session"

# 3. Attempt to use either client shipped with the repository:
python3 clients/web/server.py --api https://127.0.0.1:8080
# or
python3 clients/telegram/bot.py --api-url https://127.0.0.1:8080 --api-token "$TOKEN" --status

# Result:
# urllib.error.URLError: <urlopen error [Errno 111] Connection refused>
```

#### Why this happens

1. **Prompt omission:** `setup.sh:192` asks `Reach the console from another machine? [Y/n]`. An operator answering `Y` generates TLS keys and expects the published doors to function. However, `setup.sh:268-293` writes `container/.env` without ever setting `API_ENABLED=1`.
2. **Door suppression:** Inside `container/entrypoint.sh:313-317`, `API_ENABLED` defaults to `0`, logging `api_disabled` and skipping `start api`.
3. **Misleading port publishing:** `container/compose.yaml:78` still publishes `- "${API_HOST:-0.0.0.0}:${API_PORT:-8080}:8080"`, so Docker opens port 8080 on the host interface pointing to a closed port inside the container.
4. **Decoupled healthcheck mask:** `container/compose.yaml:94` branches on `API_ENABLED`: when `0`, it checks only `pgrep -f 'python3 -m flock.switch'` and `redis-cli ping`. The container reports `healthy` despite the API service being dead.
5. **False assertion on finish:** `setup.sh:362` prints `api ${SCHEME}://127.0.0.1:8080` unconditionally, directing the operator to an endpoint that was never started.

### Secondary Failure: State Wipe on Reconfiguration

If an operator discovers `API_ENABLED=1` from `container/.env.example:7` and adds it to `container/.env`, any subsequent run of `./setup.sh` (e.g. to add an agent or adjust provider settings) executes `setup.sh:293` (`} > container/.env`), completely wiping `API_ENABLED` back to unset (0). The tenant boots on restart with the API door silently extinguished.

### Tertiary Failure: Healthcheck Injection Vulnerability

When `API_ENABLED=1` is set, `container/compose.yaml:94` executes:
```sh
curl -fsS -H "Authorization: Bearer $$API_TOKEN" http://127.0.0.1:8080/health
```
Because `$$API_TOKEN` is passed directly inside an unquoted/interpolated shell string in the container's healthcheck command, any token containing whitespace, double quotes, or shell metacharacters causes `curl` syntax errors, failing the probe and driving the container status to `unhealthy`.

---

## 3. Section 2: Review of moving observers to the watchdog (`94144f5`)

### Architectural Merits

1. **Forwarding thread purity:** Moving `ActivityTailer`, `PresenceSampler`, and `DeliveryVerifier` out of `src/flock/switch/service.py` ensures the switch only performs L2 ingress/egress queue operations. The forwarding loop is freed from file I/O (`window.log.jsonl`), Redis stream reads, and heuristic verifications.
2. **Isolated observer error boundaries:** In `src/flock/watchdog/service.py:327-342` (`run_observers`), each observer is executed inside its own `try...except` block with explicit job attribution (`watchdog._error(name, exc)`). This resolves the switch's legacy pattern where a single observer error aborted all subsequent observer evaluations for that tick.
3. **Dual cadence preservation:** In `src/flock/watchdog/service.py:379-407`, observers execute at `ACTIVITY_POLL_SECONDS` (2s) while heavy tmux inspections (`_check_stalls`) execute at `WATCHDOG_INTERVAL` (30s), avoiding unnecessary shell-outs.

### Critical Defect: Coupling Telemetry to `WATCHDOG_ENABLED`

1. **Silent telemetry collapse:** In `src/flock/watchdog/service.py:345` and `container/entrypoint.sh:298`, setting `WATCHDOG_ENABLED=0` prevents `flock.watchdog` from launching.
2. **Cascading loss:** Because observers were moved exclusively into `flock.watchdog`, disabling the watchdog (intended to silence human alerts) now shuts down `ActivityTailer`, `PresenceSampler`, and `DeliveryVerifier`.
3. **Impact on external consumers:**
   - `GET /agents/{agent}` always reports `presence.state = "unknown"`.
   - `GET /agents/{agent}/activity` stream remains empty.
   - `clients/telegram/bot.py:328` receives no activity events and cannot display progress indicators.
   - `clients/web/` activity panel becomes permanently blank.

### Documentation Drift

Commit `94144f5` invalidated existing documentation invariants:
- `docs/LLD-watchdog.md:88` and `docs/LLD-watchdog.md:230` state: *"The switch is the sole writer of blocked; the watchdog never derives or clears that state."* This is now false: `DeliveryVerifier` in `flock.watchdog` is the sole writer of the `blocked` hash.

---

## 4. Section 3: Settlement on `clients/telegram/bot.py` and the opt-in API door

As author of `clients/telegram/bot.py`, the contract and operational stance are settled as follows:

### 1. Opt-In Policy Decision: Retain, Do Not Revert

The security rationale in commit `a4c32a5` is sound and justified:
- The API door relies on a single shared `API_TOKEN`.
- In `src/flock/api/app.py:617-635`, the `as` field on posted envelopes is a declaration of identity, not a cryptographic signature. Any client possessing the token can post as any enrolled `port_type: api` client (including `telegram`).
- Headless deployments communicating strictly over tmux panes and Redis queues have no requirement for an exposed HTTP listener.

### 2. Required Setup Harmonization

The opt-in posture must be made coherent across the setup lifecycle:
1. **Interactive opt-in:** `setup.sh` must explicitly ask whether external API client access is needed (`Enable API door for external clients / Telegram / Web Console? [y/N]`), writing `API_ENABLED=1` when selected.
2. **Accurate status output:** `setup.sh:362` must only announce the API endpoint if `API_ENABLED=1`. When disabled, it should report: `api: disabled (enable with API_ENABLED=1 in container/.env)`.
3. **Client error messaging:** In `clients/telegram/bot.py:44-63`, connection failures to the API door should catch `URLError` / `ConnectionRefusedError` and log:
   `"Failed to connect to h-flock API at %s. Ensure tenant is up and API_ENABLED=1 is set in container/.env"`.

---

## 5. Summary of findings

| Area | Status | Finding | Action Needed |
|---|---|---|---|
| `setup.sh` | **Broken** | Setup generates TLS and advertises API door at `:8080` while leaving it disabled (`API_ENABLED=0`). | Prompt for API enablement and write `API_ENABLED=1` in `container/.env`. |
| `setup.sh` | **Defect** | Re-running setup wipes manual `API_ENABLED=1` configuration. | Preserve existing `.env` variables during overwrite. |
| `flock.watchdog` | **Architecture** | Setting `WATCHDOG_ENABLED=0` disables telemetry (`activity`, `presence`, `verification`). | Decouple observer loop from human stall alert disabling. |
| `docs/LLD-watchdog.md` | **Drift** | LLD claims switch owns `blocked` hash writer role. | Update LLD §3 and §7 invariant 4 to name `watchdog`. |
| `clients/telegram/` | **Settled** | Opt-in policy upheld; client error reporting needs explicit `API_ENABLED` hint. | Retain opt-in; improve connection refused diagnostics. |
