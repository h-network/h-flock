# BUILD 96 results — unicast conservation control

## Result

The general conservation claim from build 92 is now behaviorally controlled on
both paths. Unicast reconciliation is an executable program, and
conservation.sh invokes that same program with the same five artifacts the
former heredoc received: ledger, container log, dead capture, ingress capture,
and injection windows.

A synthetic unresolved forward produces:

    RECONCILE sent=1 delivered_once=0 duplicates=0 dead=0 stranded=0 indeterminate=1 lost_attributed=0 lost_unexplained=0
    INDETERMINATE_FORWARD 1 sid

It exits 5. It does not print LOSS_UNEXPLAINED and does not retry.

## Extraction equivalence

Before trusting the extracted program, I executed the original heredoc from
base 5665938 and the extracted executable against the same five static
artifacts. Both exited 5 and their complete stdout was byte-identical:

    BASE=5665938
    OLD_RC=5 NEW_RC=5 OUTPUT_DIFF_RC=0

The shipping shell no longer contains a second implementation: it invokes the
executable directly. The behavioral control therefore executes the same
reconciler that conservation.sh ships, rather than an adjacent reimplementation.

## Negative control

I removed the indeterminate append and continue from the executable, leaving
the unresolved frame to fall through to loss classification. The focused test
failed at the intended behavioral locus:

    AssertionError: assert 1 == 5
    LOSS_UNEXPLAINED 1 sid none
    CONTROL_EXIT=1

The mutation was restored before the green run.

## TEST SIGN-OFF

    claim            unicast reconciliation carries an unresolved forward_unknown as indeterminate, exits 5, reports no loss, and the shipping harness invokes the controlled executable
    source sha       c92972becafa38152eb205679c73801b8155ba7b
    artefact         COMMIT
    host             local — static artifact reconciliation; no Redis, container or timing dependency
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         live conservation run, Docker, Redis, process injection, broadcast reconciliation behavior already controlled by build 92
    population       497 tests and 5 subtests; all repository tests collected

    control          remove the forward_unknown indeterminate classification so the frame falls through to unexplained loss
    expected locus   test_unicast_unknown_is_indeterminate_not_loss return-code assertion
    observed locus   same
    signature        AssertionError: assert 1 == 5; mutated reconciler printed LOSS_UNEXPLAINED 1 sid none

    evidence         docs/evidence/build-96-c92972b-control.log sha256 2c180b4e63905cf1c072bcfc2d660da52a99b38bf143449e3576d0869d3dbfb3
                     docs/evidence/build-96-c92972b-equivalence.log sha256 60d93ce01ebdc3272c652a0fea4995474b8746003203841bc6e523ed4620b82d
                     docs/evidence/build-96-c92972b-pytest.log sha256 09cd22bd9c17ad0bc02f215d0defd19da18b596626c694e7286e9399ed6498ad

    verdict          PASS
    VERIFIED BY      PENDING — assigned by architect

## Citation gate

    source sha       ea7e13e20e03063a2bca35e0c1008d101acd8992
    artefact         COMMIT
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 71 near misses
    evidence         docs/evidence/build-96-c92972b-citations.log sha256 8772008c598dfa36db46b06b8e050b9cb3dfe39af57f841fb9f843ce0d98b4d6
