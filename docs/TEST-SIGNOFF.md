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
                   ⚠ the path must be IMMUTABLE — see below

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

## ⚠ Evidence must sit at an immutable path

**A hash and a read are one claim only if nothing can change between them.**

`evidence /tmp/build-NN.log sha256 <hash>` looks rigorous and is not. `/tmp` is
mutable and shared: the author re-runs, the file is overwritten in place, and the
hash in the document now describes content nobody can produce again. Every later
reader — including the author — is quoting a file they cannot prove they read.

**Do this instead:**

1. **Snapshot first**, to a path nothing will rewrite:
   `cp /tmp/build-NN.log docs/evidence/build-NN-<sha>.log`
2. **Hash the snapshot**, not the original.
3. **Quote from the snapshot** in the sign-off and in any refusal.

⚠ **A refusal that asserts what an artifact contains must QUOTE the lines**, not
summarise them. A summary of a file the reader cannot re-open is unfalsifiable,
and the author's only options are to comply blindly or to argue from a second
unverifiable reading.

⚠ **And if an author complies with a refusal without pushing back, RE-READ.**
Compliance is not confirmation. Build 88 came within one commit of having two
working negative controls rebuilt to satisfy a finding that was mistaken — the
verifier asserted from a mutable path, the author regenerated the evidence rather
than checking, and the original artifact was destroyed by that regeneration.
⚠ **The architect made the same evidence-association error in the same hour**,
hashing and then reading `/tmp` in separate steps, and was saved only by the
order the writes happened to land in. **This rule is not aimed at lanes.**

**Both roles are covered by one habit: snapshot, hash the snapshot, quote the
snapshot.**

### ⚠ Reading the source is not a control — least of all for a documentation build

⚠ **A documentation build fails differently and its usual gates cannot see it.**
`pytest` does not read prose. The citation checker proves a path and a line
**exist**, never that the sentence beside them is true. So a doc can pass every
gate while asserting something the code does not do — and the doc is what the
next implementer believes.

**Build 93 shipped a `CONTRACTS.md` paragraph restoring the exact control
contract that build 91 had spent four refusals withdrawing**: `_failed` before
state changes, `_incomplete` after partial mutation. The code does neither — any
exception from a write yields `_incomplete` with `outcome UNKNOWN`, including the
first. `tests/test_control.py` already proved it. Its sign-off said *"control:
checked against source implementations"* and claimed `PASS`.

⚠ **`tmux` named the cause exactly: the assertion escaped BECAUSE source reading
was used as a control.** Reading is how the claim was formed. A control has to be
able to contradict it.

**The control for a documentation build is a TEST THAT ASSERTS THE DOCUMENTED
SENTENCE.** Write the claim as an assertion and run it. If it passes, the
sentence is true of this tree; if it fails, you have found the defect the prose
would have shipped. ⚠ **A claim with no such test is not verified — it is
believed**, and the sign-off must say `SMOKE`, never `PASS`.

⚠ **Contradictions inside the file you are editing are IN SCOPE**, however
narrowly a build is drawn. A scoping instruction that says "do not sweep other
documents" does not license leaving the edited document at war with itself —
`CONTRACTS.md` gained the async limit at one line while still saying *"StartAgent
… creates the window"* at another. **Reconcile it, or record it as drift by
name.**

### ⚠ Bind each gate to the tree it actually ran against

A test gate binds to the **code** commit. A citation gate validates
**documents**, so it binds to the **docs** commit — and those differ whenever a
results file lands after the code.

⚠ **Build 91 recorded 0 hard / 52 near beside a code SHA where the checker
actually says 58.** Every hash matched and the artifact was authentic; it was
produced at a different commit than the line named. **A field naming the wrong
TRUE thing is harder to catch than one naming a false thing** — build 88's
non-existent sha was found in one command, this took a verifier re-running the
checker at the named commit.

**The number must reproduce at the commit printed beside it. Check that it does.**

### ⚠ The recursion, and how to bind through it

A results document that records a citation-gate result **is itself a document
the gate checks**, so writing the answer down can change the answer.

⚠ **Do NOT solve this with commit choreography.** The first answer here was
`bus`'s — bind to the pre-results commit and have the sign-off exclude the
binding edit, proving that diff is limited to the field and the artifact. It is
sound, and **it broke the first time anything else was corrected**: a one-word
prose fix landed after the binding, the excluded diff grew a third member, and
the claim needed a fresh pre-results commit and a fresh binding commit to be true
again. A rule that requires re-doing a two-commit dance after every correction
will be got wrong.

**Bind to the FINAL commit, and prove the number reproduces there.**

```bash
git archive <final-commit> | tar -x -C /tmp/verify
cd /tmp/verify && python3 tools/check_citations.py
```

⚠ **The number a sign-off records must be true of the tree that CONTAINS the
record.** That is the tree anyone will check out, it needs no exclusion clause,
and it verifies in one command instead of an argument about what a diff touched.

**On the recursion itself:** writing the count down can only move it if the
written text adds or removes a `path:line` citation — and a binding block records
numbers and shas, not citations. So the record is a **fixed point** by
construction, and *measuring at the final tree proves it is one.* If it ever is
not, iterate: write, measure, correct, measure again, until the recorded number
is the number that tree produces. ⚠ **An evidence `.log` is not scanned** — the
checker reads Markdown — so adding an artifact cannot move the count either.

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
