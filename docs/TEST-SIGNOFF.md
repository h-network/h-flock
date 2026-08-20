# Test sign-off

⚠ **A test result is a claim. This is the shape it must take to be one.**

Every field exists because a run in this repository was reported as evidence and
was not. **A missing field is not a pass.**

---

## The form

```
TEST SIGN-OFF

  claim            what this run establishes, in one line
  source sha       <full sha>            ⚠ the commit, not "main"
  artefact         COMMIT | WORKING TREE | <digest of what actually ran>
  host             lab 172.16.0.14 | h-oracle | local | NOT MATERIAL (+ why)
  command          the exact command
  exit status      <n>                   read UNPIPED

  EXCLUDED         paths and populations this run did NOT exercise
  population       what the aggregate is over: n of N

  control          what was MUTATED to make the property false
  expected locus   where the failure should surface
  observed locus   where it actually surfaced        ⚠ must match
  signature        the failure's text / code

  evidence         <path> + sha256 if it will be torn down

  verdict          PASS | REFUSED | SMOKE
  VERIFIED BY      <lane>   author of the change?  YES | NO
```

**Conditional blocks — fill only when they apply:**

```
  DESTRUCTIVE      identity this run CREATED · what teardown touches ·
                   protected names refused (and the refusal proven)

  COMPARISON       baseline sha · same host · same session · interleaved?
```

---

## The three rules that decide the verdict

⚠ **1. If `EXCLUDED` intersects the claim, the verdict is REFUSED.**

Mechanical, no judgement. `bus` constructed a sign-off that filled every other
field honestly and was still false:

```
claim      checker refuses DANGEROUS
control    missing file exited 1
EXCLUDED   no readable DANGEROUS input exercised
verdict    PASS          ← the exclusion CONTAINS the claim
```

⚠ **2. A control must mutate the property, and fail where it should.**

That same counter-example had a control that genuinely failed — in
`Path.read_text`, before any content oracle ran. The property was never
exercised. **`expected locus` and `observed locus` are why the form now asks
where.**

**BUILD 62**: a negative control passed for the wrong reason — it withheld the
launcher instead of exercising the condition.

⚠ **3. No control means SMOKE, never PASS.**

`NOT ESTABLISHED` plus `PASS` used to be syntactically legal here, which made the
field unfalsifiable — nobody ever failed it. **SMOKE** is the honest outcome for
a useful run without controls, and it is not evidence.

---

## Why each field, with the run that earned it

| field | earned by |
|---|---|
| **artefact** | a watchdog fix "verified live" on h-oracle from an uncommitted **working tree**, while the commit sat on the wrong branch and `main` never moved |
| **exit status, unpiped** | **BUILD 55** — `accept.sh` counted **24 plumbing failures** and returned green, because the pipeline reported the consumer's status |
| **EXCLUDED** | **BUILD 29/33** — `clients/telegram/bot.py` had `def enrol():` missing `self`. Pytest green on mocks; it excluded ever instantiating the client. **The live bot crashed on call #1** |
| **population** | **BUILD 70** — a `sent → popped` median from **100 enrolment paths** while the workload had 2,000. Plausible number, wrong population |
| **control / locus / signature** | **build 78's counter-example**, above |
| **DESTRUCTIVE** | **BUILD 59** — teardown killed the live office because the compose project was derived from the tenant name and ran `down -v` |
| **COMPARISON** | **BUILD 68** would have reported a 21% regression against a historical figure; paired on one host it was **−2.11%**. Identical scripts read **6.5/s on the lab and 853/s on h-oracle** |
| **VERIFIED BY** | **BUILD 77** — three commits authored, implemented and self-reviewed by `architect` shipped two defects, both found by `api` on first independent read |

`WORKING TREE`, `NOT MATERIAL`, `SMOKE` and `NO` are all legal answers. Each
changes what the run means; none of them is a failure to report.

⚠ **Anyone may attack; only an independent reader signs.** Required where the
change is load-bearing — contracts, wire or custody, destructive paths,
harnesses, or a measured claim. Mechanical prose may be peer-landed with the
scope declared.

---

## Two examples

**PASS** — the citation recogniser's case blindness, build 78:

```
  claim            the recogniser sees a citation regardless of extension case
  source sha       <this commit>          artefact COMMIT
  host             NOT MATERIAL — hermetic, no I/O outside tmp_path
  command          python3 -m pytest -q tests/test_citations.py
  exit status      0                      read unpiped
  EXCLUDED         container build, accept.sh, every runtime path
  population       3 constructed citations, both cases, both arms
  control          an upper-case citation to a path absent from the tree
  expected locus   the recogniser, reported as "path does not exist"
  observed locus   same                   signature: "… path does not exist"
  evidence         tests/test_citations.py
  verdict          PASS
  VERIFIED BY      bus — author of the change? NO
```

**REFUSED** — my own watchdog verification, 2026-08-19:

```
  claim            the observers survive WATCHDOG_ENABLED=0
  source sha       f33885a                artefact COMMIT
  host             lab 172.16.0.14
  exit status      0
  EXCLUDED         accept.sh, every HTTP-enrolling scenario, the tmux paste path
  control          NOT ESTABLISHED — the pre-fix tenant was never run
  evidence         /tmp/b77-build.log — torn down, no sha256
  verdict          REFUSED                VERIFIED BY architect — author? YES
```

⚠ **Two fields sink it.** The control was *asserted*, not induced, so nothing
distinguishes "the fix works" from "the observers were always going to write
those keys" — and the author signed it. **That run is in this repository and was
reported as verification.**

---

⚠ **This document is not a gate.** Nothing enforces it. `bus` scored **BUILD 55**
against it and could not fill the run sha, working-tree identity, host binding,
exact command, or retained evidence — **our best-documented negative control
cannot be signed off retrospectively.** That gap is the argument for filling the
form while the run is happening rather than after.
