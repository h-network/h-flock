# BUILD 80 results — writer provenance

## Result

Every custody record now names the process that wrote it. The ordinary path
uses the module as its default writer; the benchmark processes label themselves
bench-send and bench-port before importing flock; watchdog and session raw
records carry their own fixed writers. WindowLogTailer preserves an explicit
writer and supplies window:<agent> only when the field is absent.

analyse-run.py accepts repeatable --writer and --exclude-writer filters, always
prints the selected writer census, and refuses a measurement whose selected
census contains an undeclared synthetic benchmark writer. A harness may declare
an exact NAME=COUNT with --expect-writer; a missing or surplus record refuses
and prints actual against expected. switch-bench declares bench-send once and
bench-port's named received/opened stage count per envelope, preserves the
analyser status through teardown, and exits with it. With no filter it still
counts the same records as before; legacy records without writer fall back to
module and produce byte-identical analysis output to records carrying that
module explicitly.

The label is provenance for analysis, not authentication. A tenant participant
can forge it; signing, uid separation and per-writer storage remain out of
scope.

The same commit also carries BUILD 81's requested watchdog construction default
from 10 to 120 seconds. tmux owns the corresponding verifier implementation and
tests; this branch changes no other BUILD 81 behavior.

## TEST SIGN-OFF — full repository gate

    claim            every implemented writer path and analyser contract passes the repository suite
    source sha       6167f8bee67746e696a29d4e86efe15c41f3355a
    artefact         COMMIT
    host             local — hermetic tests and citation reads; no live tenant behavior claimed
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container build, accept.sh, live tenant, throughput and destructive paths
    population       409 tests and 5 subtests; all repository tests collected

    control          three property mutations documented below
    expected locus   writer default, analyser exclusion, and tailer preservation respectively
    observed locus   same for all three
    signature        each named test failed with exit 1 and the deliberately wrong value visible

    evidence         /tmp/build80-pytest.log sha256 5022c47f740da75c6565a4ae6429c8deb76e9d8c4f19c9609f9cad20a47aed81

    verdict          PASS
    VERIFIED BY      tmux — author of the change? NO

## Controls

### 1. Default writer and legacy census

Property mutation: changed the log_record fallback from module to
wrong-default.

    command          pytest -q tests/test_window_logging.py::test_record_writer_defaults_to_module_and_accepts_process_label
    exit status      1, read unpiped
    expected locus   log_record default-writer assertion
    observed locus   tests/test_window_logging.py, expected switch and observed wrong-default
    signature        AssertionError: assert 'wrong-default' == 'switch'
    evidence         /tmp/build80-control1.log sha256 8aaff9497b59e04bfd9a2d4479c3ae5703128dd9d1bc711c98d3674219c7131b

The restored tests also compare a legacy six-record path with no writer against
the same path with writer equal to module. Both return 0 and their complete
analysis output is identical, including writers: test=6.

### 2. Synthetic writer exclusion

Property mutation: disabled the excluded-writer membership branch while leaving
argument parsing and the census intact.

    command          pytest -q tests/test_fabric_log_metrics.py::test_writer_census_refuses_synthetic_and_exact_exclusion_restores_run
    exit status      1, read unpiped
    expected locus   analyser exact-exclusion assertion
    observed locus   tests/test_fabric_log_metrics.py, excluded run returned 1 rather than 0
    signature        AssertionError: assert 1 == 0
    evidence         /tmp/build80-control2.log sha256 6729c2dada8c65437fb9846f9745b63a2fa6314fefb723e8c21d030b4064435a

Restored behavior counts bench-send=6 and port=6 and refuses the unfiltered
measurement. Excluding bench-send removes those six records exactly, leaves
port=6, and returns 0.

### 3. Tailer preservation

Property mutation: made WindowLogTailer enter its fallback arm even when writer
was already present.

    command          pytest -q tests/test_window_logging.py::test_window_tailer_adds_absent_writer_and_preserves_explicit_writer
    exit status      1, read unpiped
    expected locus   tailer explicit-writer preservation assertion
    observed locus   tests/test_window_logging.py, custom-port became window:unknown
    signature        AssertionError: assert 'window:unknown' == 'custom-port'
    evidence         /tmp/build80-control3.log sha256 7482a264d45d33b500846c6571fd4cf86d0722c68e4c28e38488248aee63eea6

After restoration, an absent writer becomes window:architect and the explicit
custom-port writer survives unchanged. The build-79 regression guard
test_no_json_record_reaches_stdout_without_the_mirror also passes in the full
suite.

### 4. Benchmark composition

The first implementation made any bench writer an unconditional refusal. That
made the default switch-bench refuse by construction: its six-stage path is
written partly by bench-send and partly by bench-port, so excluding either
writer destroys coverage. tmux found this by composing the scripts after the
initial sign-off.

The correction keeps refusal as the default and accepts synthetic writers only
when switch-bench declares their exact census. The restored test accepts
bench-send=6, then supplies bench-send=5 over the same six records and observes
exit 1 with bench-send count 6 != expected 5. A second regression test pins the
named BENCH_PORT_STAGES count, both declarations, status capture, teardown, and
the final exit with the analyser status.

## Citation gate

    source sha       6167f8bee67746e696a29d4e86efe15c41f3355a
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    population       671 citations, 545 unique
    result           0 hard failures, 46 near misses
    evidence         /tmp/build80-citations.log sha256 6f4f95bd0a2d2ceba29c3e54029ea682e30ad13fbdea38f29292c862f021131c
