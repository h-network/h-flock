# BUILD 95 results — a provably failed kick is partial

## Result

`control.runner._kick` no longer swallows a `Popen` `OSError`. It raises a
typed `ProvableActualFailure`, and `resume_agent` records
`resume_agent_partially_failed` when earlier desired or actual work was acknowledged
before that known failure. The failed kick is named as failed and is absent
from `actual acknowledged`; the envelope dead-letters and control does not
retry it.

The living control contract now names the fourth control outcome, and
`LLD-port-tmux` distinguishes an exception's `board_write_unknown` from the
returned-invalid-depth `board_write_failed` case.

## Outcome decision

`_partially_failed` is the third semantic shape the kick needs:

- `_accepted` is false because the requested kick did not happen.
- `_incomplete` is false because no reply is missing: `Popen` rejected the
  spawn and reaped the failed child, so the non-occurrence is known.
- `_failed` is false for the whole control operation because the paused marker
  removal, window resume, and any earlier kicks were acknowledged facts.

`_partially_failed` says exactly that a named subset was acknowledged and a later named
action provably failed. The reason keeps desired acknowledgements, actual
acknowledgements, and the failed action separate. This preserves Build 91's
rule without stretching UNKNOWN or erasing facts.

## Behavioural control

Against source `338edd35ba2df6f4d29d1478724f6f23add61b75`, `_kick` was mutated
to swallow the `Popen` exception and return normally again. The end-to-end
control-runner test failed at its expected locus with `DID NOT RAISE
ProvableActualFailure`; captured output was `resume_agent_accepted`. That is the
original defect, not a nearby failure.

## TEST SIGN-OFF

    claim            a Popen OSError cannot become an acknowledged kick; prior facts plus the known failed kick produce resume_agent_partially_failed
    source sha       338edd35ba2df6f4d29d1478724f6f23add61b75
    artefact         COMMIT
    host             local — deterministic Popen, tmux and Redis doubles
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container image/build, accept.sh, live tmux, live process spawn
    population       497 tests and 5 subtests; all repository tests collected

    control          restore the swallowed Popen OSError by returning from _kick
    expected locus   test_resume_provable_kick_failure_records_partial_without_acknowledging_it
    observed locus   same
    signature        DID NOT RAISE ProvableActualFailure; captured resume_agent_accepted; exit 1

    evidence         docs/evidence/build-95-338edd3-control.log sha256 06d5e3b2350dbca9e3d9df531251fe3c0cdbcb147e07fd3745e1f8e36fd8ee9b
                     docs/evidence/build-95-338edd3-pytest.log sha256 f5622a7ba3c6f9eeea553673e583ddd9fdc856e8dc2083cb0516b73b1fbe304f

    verdict          PASS
    VERIFIED BY      PENDING — assigned by architect; author of the change? NO

## Citation gate

    source sha       9519b30c22095d13220383b48e26cc4a82844d03
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 76 near misses
    evidence         docs/evidence/build-95-338edd3-citations.log sha256 c57fe19c25f0e38ff36942da88eb0773f1322c72e7dce4956f4c7404b581fd37
