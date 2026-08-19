# h-flock vs h-vab — switch, logging, security

> **Read at:** h-flock `94144f5` (987 commits) · h-vab `a8af071` on `main`
> (547 commits, 2026-08-19 00:25). ⚠ **Both move.** h-vab moved 223 commits in
> the ten hours before this was written; re-pin before quoting anything here.

⚠ **Scope: the fabric only** — the switch, the custody log, and the security
posture around them. **Not** the office: hire, tmux, providers, presence, the
board. h-vab has none of that and does not intend to; nothing below bears on it.

## 0. What this comparison does NOT establish

Stated first because the rest is easier to over-read.

- ⚠ **No throughput comparison is made, and none is possible from what exists.**
  h-vab's `popped -> forwarded` is 4.7 ms (148 pkt/s) / 5.8 ms (40 pkt/s) and
  **excludes the ingress pop and the egress enqueue by construction**. h-flock's
  3.35 µs is `parse_for_switch` alone — the header read, not the span. Different
  spans, different hosts, different definitions. Comparing them is the error
  h-vab's own `RESULTS.md` §2 says produced four wrong conclusions.
- **I have read perhaps 600 of h-vab's ~4,600 source lines.** Every claim below
  about their code is from the file cited; nothing is from having reviewed the
  whole.
- **Their measurements are self-reported** by the process that wrote the code.
  The care is evidence — they retract figures with the arithmetic named — but
  nobody outside that run has reproduced them.
- **h-flock has been run under a real workload; h-vab has not.** Two five-hour
  four-lane sprints, no strand, no duplicate, nothing noticed. h-vab has never
  met an agent, a CLI, or a model that emits code fences.

---

## 1. The switch

| | h-flock `switch/service.py` (249 lines) | h-vab `switch.py` (556 lines) |
|---|---|---|
| **progress** | ⚠ **edge-triggered kick, sole path.** Lose it and the frame sits in ingress forever | **lossy hints + unconditional sweep.** *"the sweep alone guarantees progress"* — a lost hint costs latency |
| **mutation** | rewrites **69 header bytes** per forward — source stamp, ttl−1, hops+1 | ⚠ **mutates nothing.** Whole-frame SHA256 at `popped` makes that checkable |
| **delivery** | `Popen` per envelope — **23 ms h-oracle, 622–677 ms lab**, ~98% of the path | **long-lived `DeliveryService`**, no spawn |
| **serialisation** | `delivering` lock held for the whole opener | one resident station per port — natural |
| **port scaling** | ⚠ **never measured** | **three-port run**: 2.00 trips/scan flat, 1.00 → 0.67 per port |
| **lifecycle** | roster membership; **no attach, no detach** | `attach` / `detach`, and `target_detached` as a distinct dead-letter reason |

⚠ **The strand is the difference that matters.** Build 73 produced one
deliberately: a frame in ingress with no successor kick and nothing in the system
that would ever collect it. `DESIGN-layers` §8 has been BLOCKED on it. h-vab
designed it out rather than detecting it.

## 2. The custody log

| | h-flock `bus/logging.py` | h-vab `events.py` |
|---|---|---|
| events | **13** | **41** |
| clock | ⚠ `timespec="milliseconds"` | wall **plus monotonic**, `mono` per record |
| failures | `dead_lettered` + a **prose `reason`** | `dropped_unroutable` · `dropped_source_mismatch` · `denied` · `target_detached` · `egress_full` · `rejected_*` ×8 |
| counters | none | contract-defined, *"never alert on a raw cumulative value"* |

⚠ **The millisecond floor is not cosmetic.** It is why the switch reads "0 ms",
and why build 72's payload sweep produced a slope out of censored data — three of
four points sat at the instrument's floor and I read the fourth as a trend.

⚠ **Prose reasons are not countable.** We found this in `tmuxhost` — six failures
sharing `event: "error"` — and it is the same defect one layer down. h-vab splits
`rejected_port_congested` from `rejected_packet_too_large` *because one is
retryable and the other never is*.

## 3. Security

⚠ **This is the widest gap, and it is a gap by absence rather than by design.**

| | h-flock | h-vab |
|---|---|---|
| process identity | ⚠ **everything is `ubuntu`** — daemons and agents alike | switch **10002**, station A **10003**, station B **10004**, group 10999 |
| agent privilege | ⚠ **passwordless `sudo`**, inherited from the base image | image default identity is **deliberately not a custody writer** |
| Redis | loopback, `requirepass` **only** when bound non-loopback | **per-principal ACLs**, Redis 7.4.2, provisioning self-test |
| custody log | ⚠ **`/proc/1/fd/1`, world-of-the-uid writable** | per-writer volumes; *"each can write its own records but cannot alter the switch's account"* |
| secrets | one shared `API_TOKEN` in the environment | `init-secrets.sh` 0700/0600, `rotate-secrets.sh` with live `WRONGPASS`/`OK` |

⚠ **Demonstrated, not theoretical.** On 2026-08-18 I forged a `forwarded` record
into a live h-flock tenant as unprivileged `ubuntu`, one line:

```bash
echo '{"module":"switch","event":"forwarded","stream_id":"FORGED-BY-AN-AGENT",…}' >> /proc/1/fd/1
```

It appeared in `docker logs` and `analyse-run.py` would count it. **Every custody
claim we have made — conservation, exactly-once, byte identity — assumes nobody
did that.** The forgery path is also the *sanctioned* path: `bench-port.py` and
`bench-send.py` both write there by design.

### 3.1 And their signing conclusion is worth taking whole

Measured (`RESULTS-MESSAGE-SIGNING.md`, HEAD): whole-frame vs payload hash
**≤ 0.1 µs**; HMAC vs SHA256 **1.5 µs**; Unix-socket hop **10.4–13.1 µs** against
a 4.7 ms forward path. So **HMAC costs 0.03%** and *"the sidecar cannot be
deferred on latency grounds."*

**They then declined HMAC anyway.**

> *In-process HMAC is rejected: **the station controls the key and signs its own
> forged packets without breach, creating false reassurance**.*
>
> *Sidecar HMAC… **out-of-band detection alone does NOT prevent inline bypass at
> the switch or store.** Calling it 'unevadable detection' overstated the
> security guarantee.*

Adopted instead: **whole-frame hashing** (tamper-evidence at rest, zero key
management) plus **POSIX isolation, ACLs and queue-shape invariants** — prevention
over detection.

⚠ **That corrects a recommendation I made.** I proposed switch-signed custody
records after the forgery above. Signing would make that forgery *detectable*,
not impossible; the store stays writable. Their framing is the better one.

⚠ **And they state their own limit**: *"Volume isolation alone cannot make check
7.26 unevadable."*

## 4. Verdict

**On the fabric — switch, logging, security — h-vab is better on every axis
checked, and the security axis was previously a tie by absence.**

**What h-flock keeps is not in scope here**: the office. Hire, tmux, providers,
the board, the round protocol — and it produced h-vab across three sprints while
its own fabric carried the traffic without incident.

### What to take without adopting anything

Four, all local to h-flock, none requiring the swap:

1. **Monotonic clock in `bus/logging.py`** — hours of work; removes the
   millisecond floor that has already produced one false result
2. **Named events instead of prose reasons**
3. **`tools/check_vocabulary_drift.py`** — the three-way name gate
4. **`tools/check_failable.py`** — audits whether a check *could* fail

### What would settle the swap

- **A run at more than three ports**, with h-flock's four agents on it
- **One real agent on it** — build 74's shape, new substrate
- ⚠ **A decision on the security model**, because adopting the fabric without
  uid separation and ACLs takes the switch and leaves the property that makes it
  worth having
