# Build 58 — conservation result

Commit under test: `ed061e9` on `tmux/build-58-conservation`.

## Result

The first required negative control passed silently. Per the build's explicit
stop rule, the harness is worthless as conservation evidence and no loss
control, 10,000-envelope run, injection, or growth measurement was attempted.

The cause is in the harness rather than the framework: its setup programs use a
heredoc with `docker exec` but omit `-i`. Docker therefore attaches no stdin;
Python reads an empty program, exits successfully, and neither writes the ledger
nor injects the duplicate. Reconciliation then balances an empty set and the
outer control reports the silent pass. This is the same false-green mechanism
already documented in `fabric-bench`: `-i` is load-bearing for an embedded
Python program.

No correction or rerun was made in this build. The failed negative control is
the result the spec requires us to preserve.

## Raw lab-local output

```text
conservation container=h-flock-conservation-tenant-1 stations=100 rounds=100 work=/tmp/conservation-evidence
== negative control: duplicate ==
RECONCILE sent=0 delivered_once=0 duplicates=0 dead=0 lost_attributed=0 lost_unexplained=0
PARSE_FAILURES docker_json=0 dead_json=0 event_ts=0
INJECTION_COVERAGE seconds=0.000 fraction=0.000000
HARNESS DEFECT: intentional duplicate passed silently
```

The scoped `h-flock-conservation` project was removed with `down -v`; the lab
was left with only the operator-owned `h-cli` container.
