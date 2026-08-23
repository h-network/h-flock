# BUILD 103 results — join a created window to its hire

## Result

A fresh tmux `StartAgent` carrying a `correlation_id` publishes that id in the
per-agent `window.cause` key atomically with roster visibility. Control still
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

Cause and membership share one Lua boundary because cleanup after a sequential
write cannot prove its own outcome after a connection loss. On a lost Lua
reply, control truthfully emits `_incomplete`; the server has nevertheless
committed both cause and roster. Redis scripts do not roll back writes before a
command error, so the script writes roster first: an error can leave membership
without attribution, but cannot leave the rejected cause-without-roster state.
A mandatory real-Redis test loses the reply and observes both values, then
forces a `WRONGTYPE` roster failure and observes no cause.

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
- Removing the roster write from the Lua boundary leaves the cause without
  membership and fails against a real redis-server.

## TEST SIGN-OFF

    claims           fresh hire and later window_created share correlation; causes are one-shot; cause-less recovery borrows none
    source sha       a4038175b7ec9b165740508372ea859649ef5c9e
    artefact         COMMIT
    host             local — deterministic Redis/tmux doubles plus mandatory ephemeral real redis-server
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         live tmux, container build, accept.sh, measured wall-clock reconcile latency
    population       513 tests and 5 subtests; all repository tests collected

    controls         remove cause publication; replace GETDEL with GET; remove stale-marker discard; remove roster HSET from Lua
    expected loci    joined event correlation; second event absence; existing-window marker removal; cause implies roster
    observed loci    tests/test_tmuxhost.py:146, :119, :167; tests/test_control.py:159
    signatures       KeyError correlation_id; borrowed id; retained stale id; real Redis roster None; each exit 1

    evidence         docs/evidence/build-103-a403817-controls.log sha256 a175811205ce646446808c4e8f892c4f53a995eb440340cdf5db023622e44dfc
                     docs/evidence/build-103-a403817-pytest.log sha256 788c1657cf69902c4ebc2553e61485ee975d01e45cca4a4e3723c118f9ce0596

    verdict          PASS
    VERIFIED BY      PENDING — assigned by architect; author of the change? NO

## Merged-tree check

`origin/main` was `ff6940dbfd606929057d109c239def2b17637391`, the branch merge base
and direct parent. The tested branch tree is therefore the merged tree. The
living `CONTRACTS.md` and `LLD-tmux-host.md` claims compose with current main.

## Citation gate

    source sha       a4038175b7ec9b165740508372ea859649ef5c9e
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 84 near misses
    evidence         docs/evidence/build-103-a403817-citations.log sha256 9c8eb21d9d49b92a1a2c876c8626c0f61ba97ea5ef7d444954054d3772ff079c
