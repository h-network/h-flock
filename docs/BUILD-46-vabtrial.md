# Build 46 — vabtrial: put one path on the h-port_type shape

> ⚠ **A trial, like build 43.** It answers whether h-flock can sit on the h-port_type
> fabric without losing what makes it debuggable. **"No" is a successful
> outcome**, and a half-migration nobody wants to throw away is the failure.
>
> **Base on `vabtrial`, NOT on `main`.** Branch `bus/vabtrial-<piece>`, push to
> origin. ⚠ **Nothing here goes near `main`.**

## 1. What h-port_type is

A separate design (`github.com/h-network/h-port_type`, branch `naming/vocabulary`),
**not built** — a settled vocabulary and flow for a forwarding fabric. Read
`docs/NAMING.md` and `docs/FLOW.md` there first. The parts that matter here:

- **three programs**: `port` (assembles the whole packet, filters before the
  switch), `switch` (two headers and a table, forwards or refuses, **never
  mutates**), `switch` (policy and other switches)
- ⚠ **the switch is a station attached to a port, not a mode of the switch** —
  which is the same conclusion h-flock reached independently
- **`attach` / `send` / `receive`** is the entire fabric API; the switch uses it
  like anything else
- **packet header, eight fields**: `version` (wire), `destination` `type` `flow`
  (client), `source` `id` `arrived` `hops` (**fabric-stamped**)
- ⚠ **attestation is structural**: the client grammar has *no slot* for the
  fabric fields. A submitted packet carrying one is **rejected**, not corrected.
  h-flock corrects and logs `source_stamped`, so a forgery reads as routine
- **addressing**: `domain/station`, qualified always inside the fabric, exact
  byte match, no wildcards or prefixes ever
- **custody boundary** at a successful append, `packet_too_large` before it, and
  egress bounded by **bytes** with `port_congested` as a real `send()` failure

## 2. Scope — adapt the design, not just swap a path

**Adapt h-port_type's design into h-flock** and report where it fits and where it
does not:

- **the three programs.** Does h-flock's shape map onto `port` / `switch` /
  `switch`, and what does not fit?
- **the fabric API.** `attach` / `send` / `receive` replacing
  `doors.send` + queue reads
- **the packet header, eight fields**, replacing the v1 envelope — including
  whether h-flock's kinds survive `type`, and `correlation_id` surviving `flow`
- **addressing** — `domain/station` where h-flock has `pod:tenant:agent`
- **attestation by rejection** rather than correction, and what that does to
  build 36's `source_stamped`
- **custody, `packet_too_large`, `port_congested`** replacing the current
  silent-loss behaviour

⚠ **The edge is the product and is not being redesigned.** Openers, the tmux
paste, presence, boards, the `office` command keep doing exactly what they do.
Their *interface to the fabric* may change; their behaviour may not. **If an
agent can tell the difference, the adaptation has failed.**

⚠ **One domain. No switch, no cross-domain, no policy** — that is h-port_type phase 1,
and it is all this build implements. The switch is a station, later.

⚠ **Where the design does not fit, say so rather than bending h-flock to it.**
The most useful output of this build is the list of places the two models
disagree and why.

⚠ **Do not rename anything in `main`'s vocabulary.** The glossary decisions are
frozen for the duration precisely because this trial may supersede them.

## 3. Pass or fail — decided now

**1. The product still works.** `bash container/accept.sh` — plumbing 25/25 and
simulator 19/19, on a tenant built by `setup.sh` the ordinary way.

**2. Custody is still answerable.** h-flock's five records exist so a lost
envelope is *locatable rather than merely absent*, and that property found two
defects last week that fifty audit rows missed. h-port_type replaces them with a
custody boundary and an observer off to the side. ⚠ **State plainly whether you
can still answer "where did this packet stop", and how.** If the answer needs a
bespoke observer as large as the thing it replaced, that is a fail — the same
criterion that ended build 43.

**3. Nothing new in the hot path.** The switch reads two headers and a table.
If it grew a branch, say so.

## 4. Evidence

Baselines from `main`, measured 2026-08-12 — reproduce, do not invent:

- 1,285 envelopes over three hours, four agents, **zero losses**, 1,283 of 1,285
  with the complete record set
- plumbing 25/25, simulator 19/19
- a short multi-agent run on the local model — **Nemotron on
  `http://172.16.0.11:8000`, free, no subscription cost.** ⚠ Use a CLI-less or
  local-model tenant; do not point a load test at a metered account

⚠ **Paste the raw output.** A verdict without numbers is not a result.

## 5. What would make this a "no"

- custody cannot be reconstructed without a bespoke observer
- the switch needs to know about anything other than two headers and a table
- the eight-field header cannot carry what h-flock's kinds need without adding
  fields the client asserts
- ⚠ **the edge has to change** — that is the product, and it is not on the table

## 6. Reporting

`jira done`, then message `architect` with the commit, what moved, the raw
evidence, your answers to §3, and a plain recommendation.

⚠ **This is a trial for one build. It is expected to end in a recommendation,
not a migration.**
