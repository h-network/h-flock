# Build 15 — seed the codex and agy first-run gates

> [`BUILD-14`](BUILD-14-cli-hardening.md) §3 documented these as gates we could
> not pre-empt, on the basis that no config key existed. **That was wrong.**
> Clearing them by hand in a live tenant and diffing the disk found every one of
> them written to a file we can seed.
>
> **Base on `main`.** Branch `tmux/build-15-cli-gates`, push to origin.

## 1. What changed and why this supersedes the research

Build 14 took "no documented config key" as the answer. Running the CLIs and
watching what they wrote gave a different one. **Prefer the experiment.** The
keys below were read off a real container on 2026-08-09 after clearing each
prompt by hand, not from documentation.

Claude already works this way — `ensure_claude_project_trusted` writes
`hasTrustDialogAccepted` per directory before the CLI starts. This build gives
codex and agy the same treatment. It is the house pattern: **pre-empt the gate,
never detect it.**

## 2. codex — trust, per directory

Written to `~/.codex/config.toml` when the directory is trusted:

```toml
[projects."/workdir/<agent>"]
trust_level = "trusted"
```

Add `ensure_codex_project_trusted(cwd)` in `flock/tmux/ops.py` alongside the
Claude one, and call it from the same place — `create_window`, so every caller
gets it and no caller can forget.

⚠ **Appending a `[projects."…"]` table is safe; a bare key is not.** Build 14
learned this the hard way — the update-check key had to be written *first*
because a bare key after a section header joins that section. A table header is
positionally independent, so appending is correct here. Do not "fix" it to match
the other one.

⚠ **Merge, do not rewrite.** `config.toml` already carries
`check_for_update_on_startup` and may carry profiles from `container/home`. If
the agent's table is already present, leave it alone rather than duplicating it —
TOML rejects a duplicate table outright, which would break every CLI in the
tenant, not just the one being enrolled.

## 3. agy — telemetry, trust, and onboarding

Two files under `~/.gemini/antigravity-cli/`.

**`settings.json`** — trust *and* the Google data-collection consent:

```json
{ "enableTelemetry": false, "trustedWorkspaces": ["/workdir/<agent>"] }
```

⚠ **`enableTelemetry` must be seeded `false`, and this is not a preference.**
The prompt agy shows is **pre-checked to opt in**, and accepting it sends agents'
interaction data to Google. An unattended agent cannot consent on anyone's
behalf, so the only safe default for a container that starts agents
automatically is off. If someone wants it on, that is a deliberate act with a
person behind it.

⚠ `trustedWorkspaces` is a **list** — append the agent's directory, keep the
existing entries. Every agent in the tenant shares this file.

**`cache/onboarding.json`** — the marker that suppresses *all three* gates:

```json
{ "consumerOnboardingComplete": true,
  "enterpriseOnboardingComplete": false,
  "onboardingComplete": true }
```

⚠ **Corrected after testing.** This spec originally named `jetski_state.pbtxt`
and it was wrong. Seeding its `post_onboarding` block changed nothing — a fresh
agy agent still met the picker, and then the consent screen **despite
`enableTelemetry: false` already being on disk**. Completing onboarding by hand
wrote exactly one file, the one above. Verified by seeding it and hiring a new
agy agent, which reached its prompt with zero keypresses.

`enableTelemetry: false` in §3 is still right and still required — it is what
keeps telemetry off once the consent screen is skipped rather than answered.

<details><summary>The wrong turn, kept because it looks so plausible</summary>

`jetski_state.pbtxt` carries exactly the block you would expect to be the
record:

```
post_onboarding:  {
  completed_steps:  POST_ONBOARDING_STEP_TYPE_MANAGER_WELCOME
  completed_steps:  POST_ONBOARDING_STEP_TYPE_USAGE_MODE
  completed_steps:  POST_ONBOARDING_STEP_TYPE_AGENT_CONFIGURATION
  completed_steps:  POST_ONBOARDING_STEP_TYPE_ADD_WORKSPACE
}
```

It reads as the onboarding record, it is written when onboarding completes, and
seeding it does nothing at all. agy writes it either way.

</details>

`onboarding.json` is **image-level, not per-agent** — it carries no path, so it
belongs in the Dockerfile beside the Claude keys.

## 4. What is now known-good

Recorded on a live tenant, all three credentials seeded by `seed-home.sh in`:

| CLI | credential | first launch |
|---|---|---|
| claude | Claude Max | straight to the prompt, bypass permissions on |
| codex | authenticated | prompt after clearing trust once; YOLO mode |
| agy | Google AI Ultra | prompt after colour scheme, telemetry, trust |

**No CLI showed a login menu.** Copying the three credential files is sufficient
for authentication; everything remaining is first-run UI.

## 5. Done when

- a freshly hired codex agent reaches its prompt **with no keypress**
- a freshly hired agy agent reaches its prompt **with no keypress**
- `settings.json` shows `enableTelemetry: false` and the agent's directory in
  `trustedWorkspaces`
- hiring a second agent of each kind leaves the first one's entries intact
- an existing `config.toml` keeps its profiles and its update-check key
- 122 tests still green

⚠ **Test hiring twice.** Every bug in this build is a merge bug, and a single
enrolment will not show any of them.

## 6. Reporting

`jira done`, then message `architect` with paths, status, and whether the
`jetski_state.pbtxt` seeding actually suppressed the picker.
