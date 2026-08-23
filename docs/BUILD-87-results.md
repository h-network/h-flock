# BUILD 87 results — office send payloads

## Result

`office send` now parses its destination and payload source instead of treating
the whole tail as message text. Mistyped options are rejected by argparse rather
than delivered as a successful message. The second `argparse.REMAINDER` belongs
to `office broadcast`: broadcast has no competing payload-source flags and its
whole tail is deliberately message data, so it was not changed.

The acknowledgement is:

    sent to DESTINATION: UTF8_BYTES bytes (STREAM_ID)

It says what destination and payload size were accepted while retaining the
stream ID used for custody tracing.

## Accepted forms

Positional text is exactly one shell argument. Quote ordinary multi-word text;
use `--` when the complete body itself begins with an option-looking token.

    office send -a NAME "MESSAGE TEXT"
    office send --agent NAME "MESSAGE TEXT"
    office send --agent=NAME "MESSAGE TEXT"
    office send -a NAME --stdin
    office send -a NAME --file PATH
    office send -a NAME -- "--stdin is literal message text"

`--stdin`, `--file`, and positional text are mutually exclusive. Empty stdin is
refused. File and stdin contents are read directly by Python and never parsed by
the shell after reading.

Both spellings below are accepted; the camel-case forms remain compatible:

    office let-go NAME
    office letGo NAME
    office clone-to-all REPOSITORY
    office cloneToAll REPOSITORY

The generated workspace agent guide at `src/flock/tmux/ops.py` and any existing
`AGENTS.md` copies must be updated to teach the quoted positional form plus the
new stdin/file forms. They are outside this build's one-product-file scope and
were not edited here.

## TEST SIGN-OFF

    claim            office send preserves explicit payloads, refuses ambiguous input, and reports destination plus UTF-8 bytes accepted
    source sha       12bf8d83056b0625a2ba7a129b9f131f1fe65d2b
    artefact         COMMIT
    host             local — parser, file/stdin fixtures, and mocked Redis are hermetic
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         live tenant, tmux paste, shell quoting performed before argv reaches Python, container build, accept.sh
    population       456 tests and 5 subtests; all repository tests collected

    control          positional branch removed the literal substring --stdin from an otherwise valid quoted body
    expected locus   exact payload assertion in test_send_preserves_a_quoted_body_containing_office_flags
    observed locus   same; sent payload lost --stdin while --file and -a survived
    signature        AssertionError comparing the complete payload dictionaries; exit 1

    evidence         /tmp/build87-negative.log sha256 534d2420c6380d6f1f156ca7c05cb1830b74722e6ef0c732902f621a1f14bf46
                     /tmp/build87-pytest.log sha256 7c0aa7ada4c98911948dbce265c39a2db86b711731e9540a6593d9c0db743be2

    verdict          PASS
    VERIFIED BY      tmux — author of the change? NO

## Citation gate

    source sha       12bf8d83056b0625a2ba7a129b9f131f1fe65d2b
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 45 near misses
    evidence         /tmp/build87-citations.log sha256 a03211736acb84d4589c79223c912ed688637866cbcd326210dd2c1ff4a38367
