# Build 50 — a lifecycle payload with an unknown key is an error

> **Base on `main`.** Branch `<lane>/build-50-loud-payloads`, push to origin.
> Owner: `tmux` (`src/flock/control/openers.py`).

## 1. The bug this prevents, which already happened

`control/openers.py` reads the participant's attachment as:

```python
agent_vab = payload.get("vab", "tmux")
```

During build 49 the server was renamed to `port_type` and nine client files were
not. A client sending the old key did **not** fail — `.get` returned the
default, and the client **enrolled as a tmux participant**, getting a window
instead of a mailbox. Green everywhere, wrong behaviour.

⚠ **The rename found it, but the rename is not the cause.** Any client typo —
`"port_typ"`, `"vab"`, `"type"` — produces a silently mis-enrolled participant
today.

## 2. ⚠ Do NOT make the field required

I considered it and it is wrong. **The default is load-bearing**:
`clients/web/flow-check.py:82` and `clients/web/tests/test_web_server.py:522`
both send `StartAgent` with no attachment key and correctly want a tmux agent.
Requiring it breaks hiring.

**Reject unknown keys instead.** That separates "you did not say" — which has a
sane default — from "you said something I do not understand", which never
should.

| payload | today | after |
|---|---|---|
| `{"agent":"x"}` | tmux | tmux — **unchanged** |
| `{"agent":"x","vab":"api"}` | **silently tmux** | **422, unknown key `vab`** |
| `{"agent":"x","port_type":"api"}` *(post-rename)* | — | api |

## 3. Scope

The lifecycle openers in `flock/control`: `StartAgent`, `StopAgent`,
`PauseAgent`, `ResumeAgent`. Each declares the keys it accepts; anything else is
a `ValueError` naming the offending key, which the door already turns into a 422.

⚠ **Name the key in the error.** "invalid payload" sends someone reading source;
"unknown payload key 'vab'" ends the investigation at the log line.

⚠ **Do not touch `Message` or the envelope itself.** Payload shapes there are
open by design — `kind` is the ethertype and openers own their payloads. This
build is about the *lifecycle* surface, which has a fixed vocabulary.

## 4. Done when

- each lifecycle opener rejects an unknown key, naming it
- the three rows in §2's table are tests
- `docs/API.md` says unknown lifecycle payload keys are refused
- `python3 -m pytest -q` green (345 on `main` at the time of writing)
- `container/accept.sh` green — ⚠ one h-flock tenant at a time on the lab

## 5. Reporting

`jira done`, then message `architect` with the commit, and say whether any
existing caller in `src/` or `clients/` was sending a key you had to add to an
allow-list — that is a finding, not a chore.
