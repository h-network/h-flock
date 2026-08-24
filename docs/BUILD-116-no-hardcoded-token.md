# Build 116 — remove the hardcoded token from three committed scenarios

**Lane: `api`. Base: `main` at `14c86e1`.** Small and mechanical.

## What

Three scenario scripts carry the same line 6:

```sh
TOKEN="${API_TOKEN:-7af3ad5eb2cac57e9ca97a953908ef09}"
```

`api-auth-and-limits.sh` · `api-concurrency-and-time.sh` ·
`api-session-and-log-privacy.sh`

⚠ **h-flock is PUBLIC**, so that constant is a secret-shaped string anyone can
read. It cannot authenticate anything on its own — `compose.yaml:54` reads
`${API_TOKEN:?…}` and refuses to start without an explicit value — **but anyone
who copied it into a real `.env` is running a password published on GitHub.**

## The fix — use the pattern this repo already has

`container/scenarios/tmux-window-loss.sh:8` does it correctly:

```sh
TOKEN="$(docker exec "$C" printenv API_TOKEN)"
```

⚠ **Read the token from the running container.** That is precedent in this tree,
not invention — do not invent a third convention. Where no container is in scope
at that point, fail loudly with `${API_TOKEN:?set API_TOKEN}` instead of
defaulting. **A scenario that cannot find a token must stop, not guess.**

⚠ **Fail the script if the token comes back empty**, with a message naming what
to set. A silent empty token turns an auth test into a test of nothing.

## ⚠ Then check whether it is the only one

`git grep -nE '[a-f0-9]{32}' -- container/` and look at every hit. **Report what
you find even if you change nothing** — a second hardcoded secret we did not know
about is worth more than this fix.

## Out of scope

⚠ **Do not rotate anything and do not touch `container/.env`** — that file is not
in the repo and is not yours. ⚠ **Do not rewrite history.** The constant stays in
past commits; it is being retired, not erased, and erasing it would mean
force-pushing a public repo's `main` for a string that authenticates nothing.

## Done means

Pushed. `bash -n` on all three, and **run one of the three against a live
container** to prove the token is actually found — a change to how a credential
is obtained that was never executed is not verified.
