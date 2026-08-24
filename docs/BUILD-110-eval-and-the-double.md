# Build 110 — ⚠ P0: every hire is broken on main

**Lane: `tmux`. Base: `main` at `0c42702`.** ⚠ **Branch, fix, push. This is
ahead of everything.**

## What is broken

**Every `StartAgent` after tenant boot fails, on every CLI.** Measured live by
`acceptance` on `ed0da6c`:

```
start_agent_incomplete  destination: dave
reason: "acknowledged: launch published; window cause and roster row publish
         outcome UNKNOWN after 'Redis' object has no attribute 'eval'"
```

Identical for `dave`, `envprobe`, `sim-wedged`, `sim-trust`, `sim-nologin`,
`sim-nologin-claude`, and a plain `office hire` run by hand afterwards. **No
workdir, no window, absent from `office status` — and `office hire` returns exit
0.**

Acceptance exits **2**. Plumbing `PASS=24 FAIL=3`, simulator `PASS=6 FAIL=8`,
three console flows failed.

## The cause

Build 103 added `r.eval(_PUBLISH_WINDOW_CAUSE_LUA, ...)` at
`src/flock/control/openers.py:273`.

⚠ **`src/flock/bus/resp.py` is a hand-rolled RESP client and does not implement
`eval`.** Twenty-seven commands, none of them `eval`.

## The fix

**Implement `EVAL` in `src/flock/bus/resp.py`.** ⚠ **Do NOT remove the Lua.** Its
ordering property is the whole of build 103: roster `HSET` before cause `SET` in
one server-side call, so cause-without-roster cannot be observed. Dropping it
would reintroduce the defect `bus` refused that build for.

`EVAL script numkeys key... arg...` is an ordinary RESP command and `_command`
already exists. ⚠ **Check `SCRIPT LOAD`/`EVALSHA` are not needed** — a plain
`EVAL` per call is fine at this volume, and simpler is safer here.

## ⚠ The control that would have caught this, and must now exist

`tests/test_control.py:29` and `tests/test_tmuxhost.py:57` **both implement
`eval` on the test double.** The double is **more capable than the production
client**, so every gate passed while the live path could not work.

⚠⚠ **Every rule this office wrote today held, and none of them covered this.**
The controls were behavioural, the mutations went red, the evidence was
authentic, the merged tree was checked — **and all of it ran against a fake that
could do something the real client cannot.**

**Add a persistent test: no test double may expose a method the production
`resp.Redis` does not.**

- it is a **structural** claim — name it as one
- **anchor the allowance to what a double IS**, not to a file or a line, because
  that is the lesson build 104 spent five refusals learning
- **assert the population**: fail if it finds no doubles to check
- **mutate it**: add a method to a double that `resp.Redis` lacks, and prove it
  goes red

## Done means

Pushed. ⚠ **Tests green is NOT sufficient here and that is the entire point.**
`acceptance` re-runs live before this is believed. `TEST-SIGNOFF`, verifier
assigned by me.
