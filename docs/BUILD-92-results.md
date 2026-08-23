# BUILD 92 results — UNKNOWN is not failed

## Result

- The five exception sites now emit `send_unknown`, `board_write_unknown`,
  `kick_unknown`, or `forward_unknown`. Their reasons state that the attempted
  operation's outcome is `UNKNOWN`; none infer non-occurrence from an exception.
  The returned non-positive board depth remains `board_write_failed` because a
  reply was received and the result is provably invalid.
- Conservation carries an unresolved `forward_unknown` in a separate
  `indeterminate` bucket and exits non-zero. It never counts that record as a
  forward or a loss, and it never retries. A later `opened`, dead-queue, or
  ingress observation settles the frame using evidence rather than the attempt
  record.
- `CONTRACTS.md` defines the UNKNOWN records, the conservation decision, and
  the canonical tenant `accounts` SET added by build 91.

## Conservation decision

Carry indeterminate forwarding as its own bucket. Counting it as forwarded can
invent custody the switch did not observe. Counting it as loss can invite a
retry after a write that actually committed, manufacturing the duplicate that
at-most-once exists to prevent. A non-green, explicitly indeterminate result is
less convenient and is the only answer that preserves both facts: the write was
attempted, and its outcome was not observed.

The bucket is unresolved rather than permanent. `opened` proves delivery; a
retained ingress frame proves the write committed and stranded; a dead copy
settles the terminal alternative. Only a frame with none of those remains
indeterminate.

## Negative controls

Both controls ran against source
`7df455fc7634cb2b22c7f868865621ff81a6f57f`.

1. Restored all five exception sites to their former `*_failed` names and
   reasons. The focused tests failed at all five exact record assertions:
   unicast send, unicast forward, broadcast forward, kick, and board write;
   exit 1.
2. Folded `forward_unknown` into unexplained loss instead of the indeterminate
   bucket. `test_forward_unknown_is_not_folded_into_forwarded_or_loss` failed
   at the missing `indeterminate.append((seq, sid))` locus; exit 1.

## TEST SIGN-OFF

    claim            five exception paths report UNKNOWN without implying failure, and conservation refuses in a distinct indeterminate bucket rather than forwarding, losing, or retrying
    source sha       7df455fc7634cb2b22c7f868865621ff81a6f57f
    artefact         COMMIT
    host             local — deterministic Redis/Popen doubles and static captured-log analysis; no external service
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container image/build, accept.sh, live Redis, real process spawn, injected connection loss against a real Redis socket
    population       493 tests and 5 subtests; all repository tests collected

    control          restore five failed records; fold indeterminate forward into loss
    expected locus   five focused record assertions; conservation own-bucket assertion
    observed locus   same
    signature        five focused tests failed; conservation assertion could not find indeterminate.append((seq, sid)); both exit 1

    evidence         docs/evidence/build-92-7df455f-pytest.log sha256 2c5739b1791f8c0491f63a375afe820c5e27d55d48caf0d2260095552214fce0
                     docs/evidence/build-92-7df455f-control-events.log sha256 d7f186061853a786e079a0b538b34f11302775d0b9ddd2b0c8fdca518374a07f
                     docs/evidence/build-92-7df455f-control-conservation.log sha256 4a7e0b9b4ef7f892f655c0344546caae73caebebe8ecfa29f881bd3c4d2dad44

    verdict          PASS
    VERIFIED BY      PENDING — assigned by architect; author of the change? NO

## Citation gate

    source sha       b67802fb54b4d852fa01ab64989a443aae5dba2b
    artefact         COMMIT
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 68 near misses
    evidence         docs/evidence/build-92-b67802f-citations.log sha256 aae0f2f2e9e26b9fdc1ba2caaa191c76ad353be61312505c38d1945b8e5b23dd

## Excluded documentation finding

`docs/LLD-port-tmux.md` still says an exception emits
`board_write_failed`. That file is owned by the tmux lane and was not changed
in this bus-lane build; it must be aligned before the living documentation is
fully consistent.
