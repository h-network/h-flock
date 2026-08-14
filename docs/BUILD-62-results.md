# Build 62 — sleep-gate results

## Result

Nine fixed-sleep gates were converted to condition polls with 15-second
wall-clock deadlines. All nine were independently proven to fail at a
one-second wall-clock deadline when only their triggering action was withheld.
Every negative control exited 97 and printed its own gate identifier; no other
failure was accepted as proof.

| step | gate | polled condition | negative proof |
|---|---|---|---|
| plumbing 2 | `agent-message` | run-unique text appears in the destination pane | send withheld, rc 97 |
| plumbing 3 | `board-ticket` | run-unique ticket appears on the destination board | add withheld, rc 97 |
| plumbing 4 | `client-enrolled` | `telegram` roster value equals `api` | StartAgent withheld, rc 97 |
| plumbing 5 | `app-to-agent` | run-unique app text appears in the agent pane | POST withheld, rc 97 |
| plumbing 6 | `agent-to-app` | run-unique reply appears in the app mailbox | send withheld, rc 97 |
| plumbing 7 | `cursor-resume` | run-unique second message appears after the saved cursor | send withheld, rc 97 |
| plumbing 8 | `second-client` | `webapp` roster value equals `api` | StartAgent withheld, rc 97 |
| plumbing 11 | `hired-environment` | hired pane environment equals the booted pane environment | StartAgent withheld, rc 97 |
| acceptance console | `console-ready` | console HTTP response equals 200 | server launch withheld, rc 97 |

Converted: **9**. Proven red: **9**. Untestable conditions: **none after the
console-launch prerequisite was repaired**.

The positive lab run produced plumbing `PASS=26 FAIL=0`, simulator
`PASS=19 FAIL=0`, a real `console http=200` observation, and `accept.sh` exit 0.
Playwright was not installed, so console browser flows were explicitly reported
`NOT CHECKED` and are not claimed here. The scoped project was removed; only
operator-owned `h-cli` remained.

The final rebased unit suite was `369 passed, 5 subtests passed`.

## Three uncounted deadline corrections

These were already polls rather than fixed-sleep gates, so they are deliberately
not included in the 9/9 count. They nevertheless repeated Build 58's bug class
and were corrected separately within `plumbing-check.sh`:

- lifecycle start: 15 iterations with one-second sleeps → 15-second wall deadline
- lifecycle stop: 15 iterations with one-second sleeps → 15-second wall deadline
- dead-letter: 20 iterations with half-second sleeps → 10-second wall deadline

All retain tight 100 ms poll cadence. The timeout is now bounded by elapsed wall
time even when an observation itself becomes slow.

## Console gate prerequisite and false-green history

The first positive run showed that the console gate was unreachable after
commit `aac5c92`. Its launcher had become:

```text
CONSOLE_PID=$(... server & echo $!)
```

Command substitution waits for the write end of its capture pipe to close. The
backgrounded server inherited that descriptor and never closed it, so the
assignment never returned and control never reached either the old sleep or the
new poll. This is about the inherited file descriptor, not the ampersand or
`setsid`. The fix launches an ordinary background subshell and immediately
captures `$!`; it is a separate commit from the nine conversions.

The console negative control initially appeared valid because withholding the
launcher avoided the hang. It therefore passed for the wrong reason: it proved
the poll could time out, but not that the real positive path could ever reach
the poll. The required positive acceptance run exposed that false-green control.

A second, independent bug made the result look green. The summary used
`${CONSOLE:+, console reachable}`. Shell `:+` tests set-and-nonempty; the string
`0` is nonempty, so `--no-console` still printed `console reachable`. Either bug
alone is visible. Together, one prevents the gate running while the other says
it ran.

The console gate **did run historically on this lab**: `/tmp/accept.log`
contains an actual console section and `console http=200` from before
`aac5c92`. It was not verified after `aac5c92` until this build. These retained
lab logs contain no console section but falsely claim `console reachable`:

- `/tmp/accept51.log`
- `/tmp/accept53.log`
- `/tmp/accept54.log`
- `/tmp/accept55-main.log`
- `/tmp/accept56.log`
- `/tmp/accept59-main.log`

The summary correction is also isolated in its own commit.

## Gate versus pacing

A sleep was classified as a gate when subsequent correctness was asserted only
after blind elapsed time. Those are the nine sleeps removed here. A pacing sleep
runs only after an observed condition is still false, limits traffic rate, or
defines an intentional failure-injection window. Poll-cadence and workload
pacing sleeps remain in scope-correct places; none substitutes elapsed time for
the condition being asserted.
