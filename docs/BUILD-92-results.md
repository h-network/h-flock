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
  record. Broadcast reconciliation applies the same rule per unresolved
  recipient; a partial commit can report delivered recipients beside an
  indeterminate remainder, never a known loss.
- Current analysers refuse custody logs containing legacy `send_failed`,
  `forward_failed`, or `kick_failed` records. Cross-version attempt semantics
  are not silently combined; historical evidence requires its matching
  analyser.
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
   bucket. The executable broadcast reconciliation control reports a partial
   commit as `delivered_once=1`, `lost=0`, `indeterminate=1`, exits 5, and names
   the unresolved recipient. Changing that classification to known loss fails
   `test_partial_broadcast_unknown_is_not_reported_as_known_loss`.
3. A returned board depth of zero emits `board_write_failed`, while a raised
   write emits `board_write_unknown`; both committed tests pin the distinction.
4. Legacy `forward_failed` input makes both static run analysis and broadcast
   reconciliation refuse with exit 4 rather than reclassifying it.

## TEST SIGN-OFF

    claim            five exception paths report UNKNOWN without implying failure, and conservation refuses in a distinct indeterminate bucket rather than forwarding, losing, or retrying
    source sha       7df455fc7634cb2b22c7f868865621ff81a6f57f
    artefact         COMMIT
    host             local — deterministic Redis/Popen doubles and static captured-log analysis; no external service
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container image/build, accept.sh, live Redis, real process spawn, injected connection loss against a real Redis socket
    population       PENDING final full-suite count; all repository tests collected

    control          restore five failed records; fold partial broadcast UNKNOWN into known loss; return invalid board depth; supply legacy forward_failed input
    expected locus   five focused record assertions; executable broadcast reconciliation; board acknowledgement distinction; both analyser version guards
    observed locus   same
    signature        PENDING regenerated immutable controls after correction

    evidence         PENDING regenerated immutable evidence after correction

    verdict          PASS
    VERIFIED BY      PENDING — assigned by architect; author of the change? NO

## Citation gate

    PENDING — regenerate and verify against the corrected final tree

## Excluded documentation finding

`docs/LLD-port-tmux.md` still says an exception emits
`board_write_failed`. That file is owned by the tmux lane and was not changed
in this bus-lane build; it must be aligned before the living documentation is
fully consistent.
