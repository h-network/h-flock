# Build 47 — atomic custody record results

Worked from main commit `5dfe56e673b0cde3d54ad32f9ad1eb5563d33988`.
Implementation commit: `d87f262` on `bus/build-47-torn-records`.

## Change

`log_record` now sends the serialized JSON and its newline through one
`sys.stdout.write` call. The code states why: with unbuffered stdout, `print`
writes the value and newline separately, allowing another container process to
place its record between them. The record-sized write remains below
`PIPE_BUF`, so peer writers cannot interleave it. A separate `flush()` follows
the complete write; it writes no record bytes and makes observation timely even
when `PYTHONUNBUFFERED` is absent.

A regression test records stdout method calls and requires exactly one call
whose value ends in a newline. `CONTRACTS` §3 now says the five custody records
are a set joined by `stream_id`, not a timestamp sequence; the queue append
precedes `sent`, so `popped` may be logged first.

## Unit evidence

```text
340 passed, 5 subtests passed in 13.56s
```

## Real tenant evidence

The exact requested load shape ran on the disposable h-lab `bus-lab` tenant:

```text
fabric-bench: 100 stations x 20 rounds on h-flock-bus-lab-tenant-1

== enrolling stations ==
  roster now holds 105 participants

== sending ==
  submitted 2000 packets in 9.3s  =  216/s at the sender

== draining ==
  expected 2000, delivered 2003
  end to end: 828.3s  =  2 delivered/s
  redis memory: 1750 KiB -> 2618 KiB

== teardown ==
  retired 100 stations
```

The delivery counter is a before/after count over the live tenant and included
three concurrent control-path opens. Record integrity was therefore checked
independently by reading the complete container log and strictly decoding every
line beginning with a JSON object. The parser exited nonzero on any malformed
line or `}{` merged-record marker.

```text
strict_json_lines=9165 parse_failures=0 merged_markers=0 total_lines=9516
custody={'sent': 225, 'popped': 2230, 'forwarded': 2229, 'received': 2229, 'opened': 2229, 'dead_lettered': 1}
```

⚠ The first run retained only that aggregate before its disposable container
was removed. It did **not** retain the dead-letter record, so its stream id and
reason cannot be recovered and it cannot honestly be attributed to teardown.
The repeat below captures every dead letter before removing the tenant.

The direct benchmark sender's 2,000 `sent` records went to the attached
`docker exec` stdout rather than container logs; the container counts therefore
must not be read as a complete five-record audit for those packets. They are
the shared multi-process stream under test for torn lines, and all 9,165 JSON
records on that stream parsed individually.

## Follow-up repeat with dead-letter capture

The first run's single aggregate dead letter cannot be called teardown
behavior: its record was not retained, so neither its stream id nor reason is
verifiable. The exact 100 × 20 shape was repeated on commit `884f8f5`, with
every dead-letter JSON object extracted before teardown. There were none.

```text
fabric-bench: 100 stations x 20 rounds on h-flock-bus-lab-tenant-1
  roster now holds 104 participants
  submitted 2000 packets in 9.5s  =  210/s at the sender
  expected 2000, delivered 2000
  end to end: 773.1s  =  3 delivered/s
  redis memory: 1482 KiB -> 2349 KiB
  retired 100 stations
DEAD_LETTERS
```

Strict parse of the complete shared container stream from the repeat:

```text
strict_json_lines=9012 parse_failures=0 merged_markers=0 total_lines=9314
custody={'sent': 200, 'popped': 2200, 'forwarded': 2200, 'received': 2200, 'opened': 2200, 'dead_lettered': 0}
```

The repeat does not retroactively identify the first record. It establishes
that a dead letter is not inherent in this load shape and supplies the missing
strict evidence without inventing a stream id or reason.
