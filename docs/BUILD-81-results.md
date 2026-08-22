# Build 81 — delivery verification unit result

## Result

The unit arm implements the proposed heuristic but does not establish its live
false-negative rate. `DeliveryVerifier` now treats later `input`, `output`, or
`tool` activity as progress, defaults its direct verification window to 120
seconds, and bounds each activity-stream read at the earliest eligible marker's
millisecond. Event timestamps remain the ordering authority after that bounded
read.

The intentional trade is a false positive: output or tool activity from a turn
that began before the paste can clear a marker without proving that paste was
consumed. That is preferable to declaring 30–92% of observed healthy deliveries
unverified. A wedged process or login prompt produces none of the three activity
kinds. The no-retry rule and the `blocked` hash shape are unchanged.

The environment fallback used by `watchdog/service.py` is owned by bus in Build
80. The exact requested integration edit is
`os.environ.get("VERIFY_AFTER_SECONDS", "10")` to
`os.environ.get("VERIFY_AFTER_SECONDS", "120")`; it is deliberately absent from
this branch to avoid overlapping that file.

## Verification

- `python3 -m pytest -q` exited 0 unpiped: 404 passed and 5 subtests passed.
- `python3 tools/check_citations.py` exited 0 unpiped: 0 hard failures and 47
  near misses.
- The live four-agent Nemotron rate is excluded and remains for architect.

```
TEST SIGN-OFF

  claim            the unit evidence reader accepts post-marker output/tool activity, rejects absent or pre-marker activity, and bounds its Redis read
  source sha       b8e9954032294360caffde5166b44b2f6558d673
  artefact         COMMIT
  host             NOT MATERIAL — hermetic in-memory Redis double and fixed timestamps
  command          python3 -m pytest -q
  exit status      0 — read UNPIPED

  EXCLUDED         live tmux paste, real CLI activity files, Redis, watchdog scheduling, four-agent Nemotron traffic, and the measured false-negative rate
  population       13 DeliveryVerifier contract tests within 404 repository tests; required five-case unit arm covered 5 of 5

  control          monkeypatch VERIFICATION_ACTIVITY_KINDS from input/output/tool back to input-only for the output-only case
  expected locus   DeliveryVerifier._input_times omits the post-marker output timestamp; poll emits delivery_unverified
  observed locus   same
  signature        _input_times returned []; emitted event was delivery_unverified

  evidence         tests/test_verification.py at b8e9954032294360caffde5166b44b2f6558d673

  verdict          SMOKE
  VERIFIED BY      api — author of the change? NO
```
