# Build 71 negative result — kicker cancelled, bound race retained

Worked from main at 2065931. Build 71 was held before implementation because
direct measurement changed its premise, then cancelled after the same code was
measured on the performance host. No production code was changed.

## Premise no longer supports the component

The specification attributed 11 ms per envelope to the switch's Popen call.
Direct lab measurements put Popen at 3.3 ms inside the container and 3.7 ms
outside it; a stdout write plus flush measured 0.003 ms. The kick is therefore
roughly 4 ms, not 11 ms.

Moving about 4 ms out of a roughly 20 ms serialized switch budget would add a
long-lived process and queue to raise a ceiling the measured workload sits
about eight times below. End-to-end delivery is dominated by the hundreds of
milliseconds between kick_started and received. The architectural exchange no
longer has the cost/benefit claimed by the build premise.

The decisive comparison ran identical scripts on the four-vCPU lab VM and on
h-oracle, a 32-core Ryzen 9950X3D:

| metric | four-vCPU lab | h-oracle |
|---|---:|---:|
| popped→forwarded | 7–9 ms | 0 ms at log resolution |
| forwarded→kick_started | 11 ms | 0 ms at log resolution |
| kick_started→received | 622–677 ms | 23 ms |
| throughput | about 6.5/s | 832/s |

The 11 ms attributed to the kick was CPU contention, not syscall cost. The
component proposed by Build 71 would optimize a cost that disappears on the
performance host. The 128-fold throughput difference also confirms that lab
throughput describes a constrained correctness host, not framework capacity.

## The specified queue bound races its consumer

The proposed sequence put ingress RPUSH followed by kick RPUSH in a Redis
pipeline, then inspected the returned kick depth in Python and rolled back when
over the bound. That is unsafe with a long-lived kicker:

1. EXEC makes both writes visible and returns their depths.
2. Before the switch examines the kick depth, the kicker can BLPOP the newest
   kick and spawn its port.
3. The switch's rollback can then remove a different kick or none at all while
   dead-lettering a frame whose delivery has already started.

Build 68's post-RPUSH rollback does not transfer: an ingress rejected for being
over its bound issues no kick, so no newly activated consumer races that
rollback. A kick queue has an already-blocked consumer.

If the design is revived, enqueue and rejection must be one atomic Redis
operation—for example a Lua script that writes ingress, writes the kick,
examines RPUSH's returned depth, and rolls back both plus writes the sender dead
queue before Redis releases the operation. It remains one round trip, but it is
not the literal post-pipeline rollback specified in Build 71.

## Build 67 CPU evidence is invalid

The same review found that the lab is a KVM/QEMU guest with four vCPUs and about
8 GiB RAM, not a ten-core machine. Current independent surfaces agree:

- nproc: 4
- lscpu CPU(s): 4; KVM full virtualization
- docker info NCPU: 4
- sysfs possible, present and online CPUs: 0-3
- guest boot: 2026-08-06, before the saved measurements

Build 67's saved a-docker-stats.tsv nevertheless contains repeated formatted
values from 780% through 1,366.48%. Build 68's saved samples repeat the same
impossible shape. A four-vCPU guest has a 400% physical ceiling under Docker's
per-core percentage convention.

Only the formatted percentages were retained. The raw cpu_stats and
precpu_stats counters needed to audit Docker's calculation were not captured,
so actual utilization cannot be reconstructed. The reported 1084% median and
1366% peak are invalid instrument output, not VM CPU utilization, and must not
be used as quantitative justification for Build 68 or later designs.

Build 68's behavioral result still stands independently: at the queue bound,
200 frames were dead-lettered with no kick, and the associated port spawns
stopped. What does not stand is the claimed magnitude of the CPU reduction.

## Status

Cancelled as a negative result before implementation. No Build 71 tenant was
created and no acceptance gate was run. The lab remains the correctness host
for conservation, fault injection and races; performance claims belong on
h-oracle. The active-consumer rollback race above remains valid independent of
the cancellation.
