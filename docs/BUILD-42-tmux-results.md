# Build 42 — tmux runtime results

The `tmux` lane reached the lab over SSH and ran an isolated `tmux-lab`
compose project on loopback ports 8120/8121. The project was removed with
`docker compose down -v` after these observations.

## Ranked findings

1. **A message accepted while a rostered window is briefly absent is lost to
   the dead-letter list, even though reconciliation recreates the window about
   one second later.** Both injections returned HTTP 202, then the adapter
   recorded `window_missing`; neither envelope was replayed after the window
   returned. Reproduce with `tmux-window-loss.sh`.
2. **Every agent can read ordinary files in every peer workdir.** The observer
   read a marker created under `/workdir/architect` in two runs. This is not a
   documentation defect: `docs/HLD.md` explicitly says the container is the
   boundary and nothing inside it is.
3. **Concurrent conflicting hires settle nondeterministically but did not
   duplicate a window.** One run settled on `claude`, the next on `codex`; both
   had exactly one exact-name `race-hire` window. An unchanged re-hire retained
   one window. I could not make the duplicate-window invariant fail in two
   invocations.
4. **I could not make credentials appear in agent environments.** Neither the
   tmux global environment nor either pane's `/proc/<pid>/environ` exposed
   `API_TOKEN`, `REDIS_PASSWORD`, `REDISCLI_AUTH`, or `REDIS_URL`.

## Cross-reading

I read the raw output on `origin/api/build-42-scenarios`. I agree that its
WebSocket request log demonstrates query-token disclosure. I disagree that the
finding is limited to container stdout: that lane's committed scenario default
and verbatim report print the complete token too, expanding the credential's
exposure into source history. This report does not repeat it.

## Raw scenario output (verbatim)

### `tmux-window-loss.sh`

```text
scenario=window-loss tenant=tmux-lab container=h-flock-tmux-lab-tenant-1 agent=observer
before windows:
architect
observer
run=1 action=kill-window-then-immediate-message
{"stream_id":"0b2cb6987de24c47a3557c48aaa24ba6","correlation_id":"68654fcc7218448f8b4d264985c28a83"}
http_status=202
dead-letter tail after run=1:
{"v":1,"kind":"Message","stream_id":"0b2cb6987de24c47a3557c48aaa24ba6","correlation_id":"68654fcc7218448f8b4d264985c28a83","ts":"2026-08-11T21:23:56.963Z","producer":"api","recipient":"observer","payload":{"text":"window-loss-1"}}
delivery log tail after run=1:
{"ts":"2026-08-11T21:23:56.964Z","module":"router","event":"popped","stream_id":"0b2cb6987de24c47a3557c48aaa24ba6","correlation_id":"68654fcc7218448f8b4d264985c28a83","producer":"api","recipient":"observer"}
{"ts":"2026-08-11T21:23:56.964Z","module":"api","event":"sent","stream_id":"0b2cb6987de24c47a3557c48aaa24ba6","correlation_id":"68654fcc7218448f8b4d264985c28a83","producer":"api","recipient":"observer"}
{"ts":"2026-08-11T21:23:56.977Z","module":"router","event":"forwarded","stream_id":"0b2cb6987de24c47a3557c48aaa24ba6","correlation_id":"68654fcc7218448f8b4d264985c28a83","producer":"api","recipient":"observer"}
INFO:     172.20.0.1:54960 - "POST /agents/observer/envelopes HTTP/1.1" 202 Accepted
{"ts":"2026-08-11T21:23:57.659Z","module":"adapter","event":"received","stream_id":"0b2cb6987de24c47a3557c48aaa24ba6","correlation_id":"68654fcc7218448f8b4d264985c28a83","producer":"api","recipient":"observer"}
{"ts":"2026-08-11T21:23:57.673Z","module":"adapter","event":"dead_lettered","stream_id":"0b2cb6987de24c47a3557c48aaa24ba6","correlation_id":"68654fcc7218448f8b4d264985c28a83","producer":"api","recipient":"observer","reason":"window_missing"}
{"ts":"2026-08-11T21:23:58.049Z","module":"tmuxhost","event":"window_created","recipient":"observer"}
windows after reconciliation run=1:
architect
observer
run=2 action=kill-window-then-immediate-message
{"stream_id":"a592fef39753459b8e70beee46cca6dc","correlation_id":"e352275a82404a63aaad8847aa1a6965"}
http_status=202
dead-letter tail after run=2:
{"v":1,"kind":"Message","stream_id":"0b2cb6987de24c47a3557c48aaa24ba6","correlation_id":"68654fcc7218448f8b4d264985c28a83","ts":"2026-08-11T21:23:56.963Z","producer":"api","recipient":"observer","payload":{"text":"window-loss-1"}}
{"v":1,"kind":"Message","stream_id":"a592fef39753459b8e70beee46cca6dc","correlation_id":"e352275a82404a63aaad8847aa1a6965","ts":"2026-08-11T21:24:05.323Z","producer":"api","recipient":"observer","payload":{"text":"window-loss-2"}}
delivery log tail after run=2:
{"ts":"2026-08-11T21:24:05.324Z","module":"router","event":"popped","stream_id":"a592fef39753459b8e70beee46cca6dc","correlation_id":"e352275a82404a63aaad8847aa1a6965","producer":"api","recipient":"observer"}
{"ts":"2026-08-11T21:24:05.324Z","module":"api","event":"sent","stream_id":"a592fef39753459b8e70beee46cca6dc","correlation_id":"e352275a82404a63aaad8847aa1a6965","producer":"api","recipient":"observer"}
{"ts":"2026-08-11T21:24:05.325Z","module":"router","event":"forwarded","stream_id":"a592fef39753459b8e70beee46cca6dc","correlation_id":"e352275a82404a63aaad8847aa1a6965","producer":"api","recipient":"observer"}
INFO:     172.20.0.1:36396 - "POST /agents/observer/envelopes HTTP/1.1" 202 Accepted
{"ts":"2026-08-11T21:24:05.747Z","module":"adapter","event":"received","stream_id":"a592fef39753459b8e70beee46cca6dc","correlation_id":"e352275a82404a63aaad8847aa1a6965","producer":"api","recipient":"observer"}
{"ts":"2026-08-11T21:24:05.756Z","module":"adapter","event":"dead_lettered","stream_id":"a592fef39753459b8e70beee46cca6dc","correlation_id":"e352275a82404a63aaad8847aa1a6965","producer":"api","recipient":"observer","reason":"window_missing"}
windows after reconciliation run=2:
architect
observer
```

### `tmux-concurrent-hire.sh`

```text
=== concurrent-hire invocation 1 ===
scenario=concurrent-hire tenant=tmux-lab container=h-flock-tmux-lab-tenant-1 agent=race-hire
claude request:
{"stream_id":"48e7bc40feb3439b8d5b2ea3ff3bb45b","correlation_id":"cb6ed846f9154b49bd3eb67765bbf246"}
http_status=202
codex request:
{"stream_id":"115687e2c82640b2bab287716ddb543d","correlation_id":"e2726cc25fe24f79ac0b3fec7f43e46e"}
http_status=202
desired state:
tmux
claude
matching windows:
race-hire|claude
all exact-name count:
1
action=unchanged-rehire using-current-launch
{"stream_id":"8b56a816b7ae4ae293e5d1fa62d55e14","correlation_id":"a1f473480d4c41b0b006a7367267f0c7"}
http_status=202
matching windows after unchanged rehire:
race-hire|768|claude
=== concurrent-hire invocation 2 ===
scenario=concurrent-hire tenant=tmux-lab container=h-flock-tmux-lab-tenant-1 agent=race-hire
claude request:
{"stream_id":"71217768c87b46aeb0481f734c673b87","correlation_id":"1763a1e5b1f445588ca4c528b1fe3b39"}
http_status=202
codex request:
{"stream_id":"cad71a6c0b7b4aa7ae45b95c5e8db6c2","correlation_id":"9b1d71e7b2bc46878dcc1a81b12c41f7"}
http_status=202
desired state:
tmux
codex
matching windows:
race-hire|codex
all exact-name count:
1
action=unchanged-rehire using-current-launch
{"stream_id":"12a9b3dd49d64034816905314beae746","correlation_id":"137fec3ad7ae447b8e9060343a50d3d0"}
http_status=202
matching windows after unchanged rehire:
race-hire|905|codex
```

### `tmux-boundary.sh`

```text
=== boundary invocation 1 ===
scenario=boundary tenant=tmux-lab container=h-flock-tmux-lab-tenant-1 writer=architect reader=observer
tmux global credential variable names observed:
agent=architect pane_pid=214 credential variable names observed:
agent=observer pane_pid=714 credential variable names observed:
action=writer-creates-marker marker=boundary-6130-1786483532
action=reader-reads-writer-marker pane-output:
To run a command as administrator (user "root"), use "sudo <command>".
See "man sudo_root" for details.
ubuntu@1e88b00970a9:/workdir/observer$
ubuntu@1e88b00970a9:/workdir/observer$ cat /workdir/architect/.boundary-probe
boundary-6130-1786483532
ubuntu@1e88b00970a9:/workdir/observer$
=== boundary invocation 2 ===
scenario=boundary tenant=tmux-lab container=h-flock-tmux-lab-tenant-1 writer=architect reader=observer
tmux global credential variable names observed:
agent=architect pane_pid=214 credential variable names observed:
agent=observer pane_pid=714 credential variable names observed:
action=writer-creates-marker marker=boundary-32182-1786483538
action=reader-reads-writer-marker pane-output:
To run a command as administrator (user "root"), use "sudo <command>".
See "man sudo_root" for details.
ubuntu@1e88b00970a9:/workdir/observer$
ubuntu@1e88b00970a9:/workdir/observer$ cat /workdir/architect/.boundary-probe
boundary-6130-1786483532
ubuntu@1e88b00970a9:/workdir/observer$ cat /workdir/architect/.boundary-probe
boundary-32182-1786483538
ubuntu@1e88b00970a9:/workdir/observer$
```
