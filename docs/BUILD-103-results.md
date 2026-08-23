# BUILD 103 results — join a created window to its hire

## Result

A fresh tmux `StartAgent` carrying a `correlation_id` persists that id in the
per-agent `window.cause` key before publishing roster visibility. Control still
returns after desired-state acknowledgements; it does not wait for tmuxhost or
interpret window presence.

On successful creation, tmuxhost atomically consumes the marker with `GETDEL`
and emits the same id on `window_created`. The join has no timer or in-memory
handoff, so the measured 4.091-second reconcile gap is not a correctness
boundary. A failed creation leaves the marker for its retry.

The stale lifecycle is deliberately conservative:

- a successful creation consumes the cause before logging;
- an already-present window causes any marker to be discarded without an
  attributed event;
- an idempotent start publishes no marker because it causes no new window;
- stop purges `window.cause` with the other classified agent state;
- a real-agent recovery without a marker emits a valid `window_created` record
  with `correlation_id` absent; the `__init__` placeholder emits no
  `window_created` lifecycle record at all.

This prefers a missing join to a false one if tmuxhost dies after consumption
and before stdout. Absence is preserved as absence; no later window borrows an
old hire's identity.

## Behavioural controls

The integrated control invokes `start_agent`, leaves Redis as the only bridge,
then invokes tmuxhost later and joins the two emitted records. The lifecycle
controls create real `window_created` records through tmuxhost rather than
asserting source text.

- Removing cause publication makes the later event lack the hire id.
- Replacing atomic consumption with a read makes a second cause-less creation
  borrow the old id.
- Removing the already-present cleanup leaves the stale id available for a
  future recovery.

## TEST SIGN-OFF

    claims           fresh hire and later window_created share correlation; causes are one-shot; cause-less recovery borrows none
    source sha       e0c85462ed3bc9598166641ddb19c3a9d2f643d8
    artefact         COMMIT
    host             local — deterministic Redis and tmux process doubles, real control and tmuxhost code
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         live tmux, container build, accept.sh, measured wall-clock reconcile latency
    population       508 tests and 5 subtests; all repository tests collected

    controls         remove cause publication; replace GETDEL with GET; remove stale-marker discard
    expected loci    joined event correlation; second event absence; existing-window marker removal
    observed loci    tests/test_tmuxhost.py:139, :112, :160
    signatures       KeyError correlation_id; borrowed correlation_id; retained stale-correlation; each exit 1

    evidence         docs/evidence/build-103-e0c8546-controls.log sha256 62cde290e34a8cc7a3c70bc6863d144aea2b31e238c17b41bd8f3b318926c30a
                     docs/evidence/build-103-e0c8546-pytest.log sha256 b00df529d4080a56d78a6c8473c42e74baa32dee59d01e5367fd97bbf8b5e9d4

    verdict          PASS
    VERIFIED BY      PENDING — assigned by architect; author of the change? NO

## Merged-tree check

`origin/main` was `ba1d3e656cabdbe325ca1fee09cd5227ccf805d0`, the branch merge base
and direct parent. The tested branch tree is therefore the merged tree. The
living `CONTRACTS.md` and `LLD-tmux-host.md` claims compose with current main.

## Citation gate

    source sha       3701cb4a9937a8b0a9030530fd163f58ed5e099e
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 83 near misses
    evidence         docs/evidence/build-103-e0c8546-citations.log sha256 142d6ce8f239d2bfc9c1a5b65fdacf8b50fbb0b1c0bdd5aff960c1fbe438abfd
