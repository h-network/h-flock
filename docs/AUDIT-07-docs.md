# Audit 07 — the docs against a night of live-run fixes

> Rules unchanged: [`AUDIT-01`](AUDIT-01-docs.md) §1 and §3 if you have them —
> otherwise: fix what you own, report what you find in what you do not, and
> **re-measure at the end**.
>
> **Base on `main`.** Branch `<lane>/audit-07-docs`, push to origin.

## 1. The gap, measured

```
                        unescape  snapshot  default-cli  quiet-log  launch-order
  LLD-session.md               0         3            0          0             0
  LLD-container.md             0         0            0          0             0
  LLD-bus-and-router.md        0         1            0          0             1
  LLD-adapter-tmux.md          0         0            0          0             0
  LLD-tmux-host.md             0         0            0          1             1
  CONTRACTS.md                 0         0            2          1             0
  HLD.md                       0         0            0          0             0
  LLD-api.md                   0         0            0          0             0
```

⚠ **Every one of these was found by running the thing, not by reading it.** The
owner drove a browser and a terminal for a night; each row below is a defect that
every test we had passed straight over.

## 2. What changed, and why it is not cosmetic

- **tmux control mode octal-escapes its output.** `%output` never carried raw
  bytes: ESC arrives as the four characters `\033`. Nothing unescaped them, so
  the terminal door has emitted unusable output since it was built — an operator
  watched escape sequences scroll past as prose. `session/control.py`
- **the snapshot showed the scrollback, not the screen.** `capture-pane -S -`
  dumped the whole history, then live updates positioned the cursor absolutely
  within a 32-row screen, so the two views disagreed and keystrokes echoed far
  below the prompt. Now: visible screen, clear-and-home first, cursor restored
  from `#{cursor_y}/#{cursor_x}`
- **a default install produced bash shells.** `setup.sh` writes `AGENT_CLIS` only
  for agents that *differ* from claude, so a single-account install wrote none —
  and the entrypoint set no `launch` key for anyone. Every agent came up a bare
  shell reading `unknown`. `container/entrypoint.sh`
- **`office` printed bus telemetry into the agent's own pane.** An agent read
  `{"module":"adapter","stream_id":…,"correlation_id":…}` off its own screen,
  reasoned that envelope ids imply a broker, went looking and found Redis.
  `office` runs in a window, so its stdout **is** the agent's screen.
  `bus/logging.py`, `office/cli.py`
- **`launch` and `profile` are written before roster visibility.** tmuxhost
  reconciles on the row appearing; anything written after is a race that builds
  a window with the wrong CLI or the wrong account. `control/openers.py`
- **`seed-home.sh check` called a file a login.** It reported "logged in"
  whenever the credential file was non-empty; a 281-byte file with an expiry of
  zero passed while every agent sat at `Not logged in`
- **`GET /agents/{agent}` returns `vab`** — added so a client need not probe

## 3. Who fixes what

| lane | files |
|---|---|
| `api` | `LLD-session.md` — the octal unescape and the snapshot contract are yours; `LLD-api.md` for `vab` |
| `tmux` | `LLD-container.md` — the default-CLI rule and what `seed-home.sh check` now verifies; `LLD-tmux-host.md` |
| `bus` | `LLD-bus-and-router.md` — the quiet-stdout rule and the ordering guarantee in `start_agent` |

`HLD`, `CONTRACTS` are mine.

⚠ **`LLD-session` is the important one.** It describes a door that has never
rendered correctly. Whatever it says about `%output` today is wrong, and the
snapshot section describes behaviour we have just replaced.

## 4. One thing to state, not bury

⚠ **`HLD` §10 says tools and a clean environment remove the *reason* to go
looking, not the ability.** An agent proved the reason was still there. Say so:
list what an agent can still see (`POD`, `TENANT`, `FLOCK_LOG_FILE`,
`VIRTUAL_ENV`, world-readable source, `ps`) and be explicit that these are
accepted, while telemetry in its own pane was not.

## 5. Reporting

What you fixed, what you found in files you do not own, what you checked and
found correct, **and the re-measured §1 table**. A column still at zero is either
a real gap or a deliberate silence, and saying which is part of the job.
