# BUILD 111 results — the delay is ours, and zero delay did not lose this run

## Host and boundary

All measurements ran on h-oracle, not the lab, in separately named projects
`h-flock-bus111`, `h-flock-bus111d`, and `h-flock-bus111z`. The protected
`h-flock-office` and `h-flock-demo-tenant-1` containers were not touched.

The switch-only clock starts when an envelope is popped from egress and stops
when the switch has written it to the recipient ingress. It excludes submission,
port spawning, paste, and Enter. The run measured 825.77/s steady state with
1000/1000 envelopes delivered and no duplicates, dead letters, strands, or
unknown forwards.

## End-to-end comparison

The same 100-envelope ring was run through plain-shell tmux ports at each
setting. Arrival is the custody condition `opened` for every sent stream, not
the elapsed time alone.

| configuration | received→opened p50 | steady state | arrival |
|---|---:|---:|---:|
| PASTE_ENTER_DELAY=0.5 | 507 ms | 19.56/s | 100/100 |
| PASTE_ENTER_DELAY=0 | 15 ms | 363.23/s | 100/100 |

The measured delay difference is 492 ms at the median (507 minus 15). In this
plain-shell run zero delay did not lose submissions: all 100 envelopes reached
`opened`. That is a result for this workload and image, not evidence that the
documented Enter-swallow failure is gone; the mitigation remains unchanged.

The default run's spawn gap was also visible: kick_started→received was 2293 ms
median, while the paste/Enter stage was 507 ms. Those are separate layers; the
README's single ~500 ms number cannot be attributed to startup alone.

## Conservation

I generated ledgers from the 100 sent custody records in each tmux run and ran
the current unicast reconciler. Both runs reported sent=100, delivered_once=100,
duplicates=0, dead=0, stranded=0, indeterminate=0, and both exited cleanly.
The current run therefore does not reproduce the historical BUILD-47 2003
delivered against 2000 anomaly. That old count remains unclassified here; this
run's evidence is 100/100 with a clean reconciliation.

## Sign-off

    source sha       65a73ca
    host             h-oracle; base image sha256:10406097c8954af16c62cf0088dea147065146bf4f667c361da96384ed02cbdc
    evidence         docs/evidence/build-111-host.log sha256 0f52a0347cfdd3990c79e90ad1cbd5bb7cd52a75ad1b3225e79dceec6186698f
                     docs/evidence/build-111-switch-summary.log sha256 876ef7dc2ff7c384010e6fcb6793206d8b748ee63813b1e6258635c375444e9a
                     docs/evidence/build-111-default-summary.log sha256 11b0624199d4d6db2b3be8c1099dea2ac051f75179df9e53a647f8727f2c9afd
                     docs/evidence/build-111-zero-summary.log sha256 a497ca69ef8332e92f443c3d1f9914ac2c5de3ef5a03d6552b26f197486185fb
    verdict          PASS — numbers separated; zero-delay arrival verified 100/100
    VERIFIED BY      PENDING — assigned by architect

## Gates

    command          python3 -m pytest -q
    result           not changed by this measurement-only build
    excluded         lab execution, h-flock-office, h-flock-demo, README.md, ENTER_DELAY source
