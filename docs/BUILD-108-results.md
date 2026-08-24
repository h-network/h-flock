# BUILD 108 results — peers say what they are

## Result

`office peers --verbose` prints one line per tmux peer with its framework and,
when present, profile and current doing-task title. Framework is read directly
from the peer's `launch` state, so an `agy` peer is reported as `agy` without
consulting usage data. The existing plain `office peers` output remains the
same comma-separated name list, including the `(lead)` marker.

The optional send-acknowledgement rider was deliberately dropped. The office
helper calls `flock.bus.doors.send`, whose `-> str` return contract exposes only
the stream id. Printing the minted correlation id would therefore require a bus
return-contract change rather than the few-line read-only CLI change allowed by
BUILD 108.

## TEST SIGN-OFF

    claim            verbose peers distinguishes claude, codex and agy and shows optional profile/task; plain peers is unchanged
    source sha       ef9f1c8
    artefact         COMMIT
    host             local
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         live tenant execution; send acknowledgement correlation_id rider
    population       516 tests and 5 subtests; all repository tests collected

    control          (1) read framework from profile rather than launch; (2) route plain peers through the enriched path
    expected locus   (1) tests/test_office.py verbose framework assertion; (2) tests/test_office.py plain-output assertion
    observed locus   same; both exit 1
    evidence         docs/evidence/build-108-controls.log sha256 4363c3d4e1d70c5295754dd79def61de73d0b2e77b83293b1921a39fdb8fec1d
                     docs/evidence/build-108-pytest.log sha256 e46c3e25fc79896353c4f7a43cfd9a41c8a3e0b93c0cf8d65ed2b43a944638bd

    verdict          PASS
    VERIFIED BY      PENDING — assigned by architect

## Citation gate

    source sha       ef9f1c8
    artefact         COMMIT
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 85 near misses
    evidence         docs/evidence/build-108-citations.log sha256 5203ede6cf5815dbaa45639303a869c56c41e78ce373f477113ca162adcb6161
