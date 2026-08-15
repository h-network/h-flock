# Build 70 results — measure from the captured custody log

Worked from main at 2963e47 and rebased through 3b106da. Five API-path runs
used unchanged main, fresh same-name tenants with down-with-volumes resets,
100 participants and 20 rounds. Analysis ran only after each static artifact
had been captured.

## Result

Per-stage medians are substantially steadier than historical throughput
figures, but trimming the delivery window is not. The middle-80% throughput
spread was 13.5%, while the full opened-window spread was only 8.7%. The
steady-state metric was therefore noisier in this series and is not a better
gate.

The stages identify both remaining cost and variance: switch forwarding was
7 ms in every run; received-to-opened was 3 ms in every API run; and the
process-spawn gap varied from 622 to 677 ms. Host contention is real, but it is
localized to spawn rather than switch work or API delivery.

| API run | steady middle 80% | full opened window | popped→forwarded p50 | forwarded→received p50 | received→opened p50 |
|---:|---:|---:|---:|---:|---:|
| 1 | 6.69/s | 6.22/s | 7 ms | 677 ms | 3 ms |
| 2 | 6.90/s | 6.73/s | 7 ms | 639 ms | 3 ms |
| 3 | 6.76/s | 6.57/s | 7 ms | 634.5 ms | 3 ms |
| 4 | 6.08/s | 6.19/s | 7 ms | 632.5 ms | 3 ms |
| 5 | 6.49/s | 6.21/s | 7 ms | 622 ms | 3 ms |
| spread, max/min − 1 | 13.5% | 8.7% | 0% | 8.8% | 0% |

All five analyses found 2,000 benchmark opened paths, zero dead letters and
zero JSON parse failures. Their sent-to-popped and end-to-end figures were
correctly refused: unchanged main sent through docker exec, so all 2,000 sent
records went to that exec session rather than the container log. The run
scripts now capture that stream and append its JSON records to the immutable
artifact after the run. No live log reader is reintroduced.

## The contaminated reference result

The first reference analyser reported 2,100 opened events for a 2,000-envelope
workload. The extra 100 were StartAgent enrolment deliveries. Its quoted 6.47/s
steady and 5.36/s full-window rates, and sent-to-popped n=100, did not describe
the benchmark population and are not carried forward.

Filtering source to bench- corrected that artifact to 2,000 paths: 6.69/s
steady and 6.22/s across the full opened window. The same filter is now an
explicit analyser option and is exercised by a test containing control paths.

## Completion cost and separation

base-run completes from queue depth and never reads Docker logs during the
workload. Each poll makes one docker-exec call whose Python process scans the
matching ingress and egress keys and issues one LLEN per discovered queue; the
cost is constant in accumulated log size, unlike the former full Docker-log
scan every second. The log is captured once after completion and analysed as a
separate static artifact.

## Negative control

tests/fixtures/fabric-log-missing-stage.jsonl contains two delivered paths and
deliberately omits received from one. Analysis reports received coverage 1/2,
refuses both forwarded-to-received and received-to-opened instead of averaging
the surviving path, and exits 1. Complete and source-filter fixtures exit 0.

## Tmux path delta

One additional fresh run used 100 tmux ports backed by plain shells, 20 rounds,
and no model launches or tokens. It delivered 2,000/2,000 with zero dead
letters and zero parse failures.

| stage | API five-run range | tmux-shell run | conclusion |
|---|---:|---:|---|
| popped→forwarded p50 | 7–7 ms | 7 ms | unchanged |
| forwarded→received p50 | 622–677 ms | 669 ms | inside API range |
| received→opened p50 | 3–3 ms | 1,073 ms | only material delta |

The tmux path differs only where expected—the paste/open stage—but its measured
median is about 1.07 seconds, not merely the configured 0.5-second delay.
Steady and full opened-window rates were 4.19/s and 4.20/s respectively.

## Evidence

The six lab artifacts and their SHA-256 hashes are:

- /tmp/baseline-main-1.log — 01a9254f7ec299c35429427789c5c6dc49622f1df6a0ae743f8ef03b76551a85
- /tmp/baseline-main-2.log — a7ae544dc57c61c8750f92c24afd4c6c9443e688492d40f993375fef0f8b6991
- /tmp/baseline-main-3.log — 3e9377b32ae38920e88f053bd32539fbca95058a8a1b86e99ec7c4c9c4d398de
- /tmp/baseline-main-4.log — 7469319511e7931ca1f0ddfc3fdcf9ff53601007acbe516edcedd27db5789cef
- /tmp/baseline-main-5.log — 5d2e6761ad8339ede05655aee85a8a6161fa5b8962e9da7c0ddd0c0fba35eb98
- /tmp/baseline-tmux-1.log — 9f7a2105ad063640a7e6958c20004bca725233f8968daa39f429d34ae8bf48fb

