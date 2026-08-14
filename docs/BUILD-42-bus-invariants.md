# Build 42 — bus runtime invariants

These are observations that must hold on a real tenant, not guarantees inferred
from unit tests. Each item names the observation that would disprove it.

| invariant | falsifying observation |
|---|---|
| A participant queue is tenant-scoped and FIFO. | A later stream ID arrives before an earlier one from the same egress, or any fixture appears under another tenant prefix. |
| A broadcast fan-out is one atomic Redis transaction over the roster snapshot. | Recipients selected for one broadcast end with different copy counts, excluding the sender, or a partial set receives a uniquely identified broadcast. |
| The queue named by the popped egress is the producer attribution. | A directly forged producer claim reaches an ingress unchanged, or a mismatch is corrected without a producer_stamped record. |
| A retired name retains ingress, egress, inbox and board data. Re-enrolling that name resumes it. | Retirement deletes one of those resources, or retained egress routes while the name is absent rather than after it returns. |
| A destructive pop is never retried automatically after an ambiguous Redis failure. | One switch step removes two envelopes, or a single envelope is forwarded twice, after one connection interruption. |
| A graceful tenant restart preserves Redis-backed custody and board state. | A named sentinel, queued envelope, or ticket present immediately before docker restart is absent after health returns. |
| Presence sampling cost is bounded independently of the approximately 1,000-entry activity history. | Redis observes an XREVRANGE count above 10 for the presence read, or sampling latency grows linearly with retained history. |
| Logs describe observations rather than repairing transport. | A maintenance or observation failure moves, retries, deletes, or dead-letters an envelope. |
| The documented boundary is an API boundary, not agent isolation. | An agent cannot read another agent workdir or tenant Redis despite the documentation saying colleagues share both trust domains; conversely, docs claim OS or Redis isolation that is not present. |

The scenarios in container/scenarios print the mutations and raw measurements.
They intentionally print no pass/fail verdict so a second reader can disagree.
