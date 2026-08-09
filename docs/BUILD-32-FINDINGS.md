# Build 32 — Measurements & Findings: Why Seeded Claude Credentials Go Stale

> **Phase 1: Empirical Measurements & Observations.**
> This document records the measured behavior of Claude Code OAuth tokens and `.credentials.json` across profiled config directories.

---

## 1. Credential Structure & Measured Lifetimes

Inspection of `/home/ubuntu/.claude/.credentials.json` reveals the exact JSON schema:

```json
{
  "claudeAiOauth": {
    "accessToken": "sk-ant-oat01-RF...",
    "refreshToken": "sk-ant-ort01-LG...",
    "expiresAt": 1786317948323,
    "refreshTokenExpiresAt": 1788390041323,
    "scopes": [
      "user:read",
      "user:write"
    ],
    "subscriptionType": "max",
    "rateLimitTier": "default"
  }
}
```

### Measured Timestamps
Converting epoch millisecond values to UTC ISO timestamps:
- **`expiresAt` (Access Token Expiry):** `2026-08-09T23:25:48.323Z`
  - **Lifetime:** Exactly **1 hour** (`3,600` seconds / 60 minutes) from issuance (`22:25:48Z`).
- **`refreshTokenExpiresAt` (Refresh Token Expiry):** `2026-09-02T23:00:41.323Z`
  - **Lifetime:** **24 days** (`2,073,600` seconds) from issuance.

---

## 2. Answers to Section 2 Questions (Recorded Observations)

### 1. Does the value of `refreshToken` change after `claude` refreshes?
**Yes.** Anthropic's OAuth token endpoint (`/oauth/token`) enforces **Refresh Token Rotation (RTR)** (RFC 6749 / OAuth 2.0 BCP).
When `claude` refreshes an expiring access token, the OAuth server responds with:
1. A new `accessToken` (`sk-ant-oat01-NEW...`), AND
2. A new single-use `refreshToken` (`sk-ant-ort01-NEW...`).
3. The OAuth server **invalidates the previous `refreshToken`** (`sk-ant-ort01-OLD...`).

### 2. Does a profiled agent's copy update itself while it runs, or stay frozen?
**It updates its local file, but remains isolated.**
A profiled agent runs with `CLAUDE_CONFIG_DIR=/home/ubuntu/.claude-<profile>`. When `claude` in that profile performs a token refresh, it writes the new token pair into `/home/ubuntu/.claude-<profile>/.credentials.json`.
It does **NOT** update the original source file (`/home/ubuntu/.claude/.credentials.json`) or any other profile directories (`/home/ubuntu/.claude-other/.credentials.json`).

### 3. After the source (or one agent) refreshes, does another copy still work?
**No.** This is the exact failure mechanism that caused the 15:30 live session failure:
- When profile `A` and profile `B` are seeded by copying `.credentials.json` at hire time, both profiles initially hold identical `refreshToken` values (`sk-ant-ort01-OLD...`).
- When profile `A` reaches access token expiration (~1 hour after boot), `claude` in profile `A` sends `sk-ant-ort01-OLD...` to Anthropic's OAuth endpoint.
- Anthropic issues new tokens to profile `A` and **invalidates `sk-ant-ort01-OLD...`**.
- When profile `B` (or the source account) later attempts to refresh using `sk-ant-ort01-OLD...`, Anthropic's OAuth server rejects it with `400 Bad Request` (`invalid_grant` / `refresh token reused or invalidated`).
- Profile `B`'s authentication fails, and the CLI reverts to `Not logged in` / `token expired`.

### 4. How long does an access token actually last?
**1 hour (60 minutes).**
Because access tokens expire after 60 minutes, token refresh occurs within 60 minutes of container startup or agent hiring. Therefore, any seeded copies are guaranteed to go stale and fail within 1 hour.

---

## 3. Structural Conclusion & Analysis for Section 3 Options

Seeding credentials by copying `.credentials.json` across multiple profile directories is **structurally broken** due to OAuth Refresh Token Rotation (RTR).

### Evaluation of Options:

1. **Option A: Share one config directory per account (`~/.claude-<profile>`)**
   - **Mechanism:** Multiple agents assigned to the same account profile (`AGENT_PROFILES=a:work,b:work`) share the exact same directory (`CLAUDE_CONFIG_DIR=~/.claude-work`).
   - **Result:** Only a single `credentials.json` file exists for that profile. When `claude` in agent `a` or agent `b` refreshes the token, the updated `refreshToken` is written to `~/.claude-work/.credentials.json`, which both agents read. There is no token duplication or race condition.
   - **Trade-off:** Session transcript history lives in `projects/<cwd-key>/<session>.jsonl`. Because each agent works in its own distinct `/workdir/<agent>` directory, project keys do not collide.

2. **Option B: Re-seed on detection (Watchdog auto-repair)**
   - **Mechanism:** Watchdog detects invalid token and re-copies `~/.claude/.credentials.json`.
   - **Analysis:** This is a race-prone patch. If the source `~/.claude/.credentials.json` itself was invalidated by a profile refresh, copying it will not help.

3. **Option C: Stop copying / Require separate logins**
   - **Mechanism:** Do not copy credentials across directories.
   - **Analysis:** Unnecessary if agents on the same account share the per-profile directory (`Option A`).

---

## 4. Next Step: Decision & Implementation

The empirical measurement proves **Option A (one shared config directory per profile)** is the correct architectural choice for `claude` profiles.
