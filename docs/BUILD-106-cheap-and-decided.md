# Build 106 — two things already decided, neither built

**Base: `main` at `b06992d`.** Branch from main, push to origin.

⚠ **Small on purpose — and the last build I called that took six rounds**, so
the scope notes below are load-bearing rather than polite.

## 1. `API.md:53` promises propagation the code does not do

`src/flock/api/app.py:651` runs `correlation_id = uuid.uuid4().hex`
**unconditionally**, discarding anything the caller sent. `docs/API.md:53` says
*"Propagated from request or minted automatically."*

**The decision is already made** and recorded on `TODO.md`: **keep minting,
correct the document.** ⚠ **Do not implement propagation.** The reasoning, which
was `api`'s and is better than the alternatives:

- **half-threading is worse than none, because it looks like it works.** A caller
  passes an id, sees it accepted, and the agent's reply through `office send`
  mints a fresh one — the thread breaks silently at the second turn
- accepting a caller-supplied id lets a client **join a thread it was not part
  of**, and `correlation_id` is the key the whole custody log joins on
- the capability is **deferred to a threading sprint covering both doors**, not
  cancelled

**Work here is one sentence**, saying the fabric mints it for every envelope.

## 2. OAuth precedence — one test, one sentence

⚠ **Authentication is PROVEN**, so do not re-establish it: 54 usage records on a
tenant with no credentials file, and this office's acceptance seat has run all
day on a token-only profile.

**What is open**: when a profile has **both** a `CLAUDE_OAUTH_TOKEN_<PROFILE>`
and a seeded `~/.claude-<p>/.credentials.json`, **which wins?**

**Establish it and write it down.** It decides one line of help text — *"paste a
token"* versus *"paste a token, and it replaces any login you have seeded"* —
and whether `setup.sh` should warn when both are present.

⚠ **A live banner is not proof.** One was observed suggesting the token wins;
that is an observation about a greeting string. **Determine it from what the
process actually authenticates as** — a usage record naming the account, or an
equivalent that cannot be produced by the wrong credential.

## Out of scope

Everything else on either row. ⚠ **`setup.sh` warning behaviour is a
consequence of the answer, not part of finding it** — report what you found and
what you think the warning should say; do not build it here.

## Done means

Pushed. Tests green. `TEST-SIGNOFF`, verifier assigned by me. ⚠ **The precedence
finding is behavioural and cannot be settled by reading** — it needs a profile
carrying both and a check of what the CLI actually authenticated as.
