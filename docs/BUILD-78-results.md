# Build 78 — attack on the test sign-off

## Material read

`docs/TEST-SIGNOFF.md` was read at
`6444b03d37bf834fcdb33d5fd67126091f96798d`.  The build instruction was read at
`160768a793a225f207057eba9c58751e2dff3442`; that commit is an ancestor of this
branch.

No product code ran or changed.  The constructed fixture is
`docs/build-78-wrong-checker.py`.  The other attack used the existing citation
checker at `e0051fb6e7229ea3eee393cffe8ebbb31f725657`.

## Verdict

The form is insufficient.  It has fields but no acceptance relations between
them.  In particular, nothing requires:

1. `EXCLUDED` not to intersect the claim;
2. `could it fail` to fail at the claimed oracle rather than before it;
3. `NOT ESTABLISHED` to force `REFUSED`;
4. the tested artefact to be bound to `sha`; or
5. an authored, load-bearing run to have a separate verifier signature.

Consequently, a reporter can fill every field truthfully except the false claim
being attacked, then write `PASS`.  The form gives a reader useful facts, but it
does not itself refuse the conclusion those facts contradict.

## Counter-example 1 — a real control that fails for the wrong reason

The attack fixture accepts every readable file.  Its only failure is opening a
file that does not exist.  Three unpiped invocations produced:

```text
SAFE file       -> ACCEPTED SAFE       exit 0
missing file    -> FileNotFoundError   exit 1
DANGEROUS file  -> ACCEPTED DANGEROUS  exit 0
```

The complete output was recorded at
`/tmp/build78-signoff.awP5e6/evidence.log`, SHA-256
`2ff15b8a2703e2961c7947c398bb80daad35024767c58a1edde94d4c791f0a3e`.

Here is a completely filled sign-off which the current form does not instruct a
reader to refuse:

```text
TEST SIGN-OFF

  claim          the checker refuses DANGEROUS content
  sha            e0051fb6e7229ea3eee393cffe8ebbb31f725657
  built from     COMMIT
  host           local — deterministic file-content check; no substrate
  run by         bus         authored the change? YES

  command        python3 docs/build-78-wrong-checker.py /tmp/.../safe.txt
  exit status    0, read directly
  evidence       /tmp/build78-signoff.awP5e6/evidence.log
                 sha256 2ff15b8a2703e2961c7947c398bb80daad35024767c58a1edde94d4c791f0a3e

  EXCLUDED       no readable DANGEROUS input was exercised by the claimed run
  could it fail  yes — the same checker against a missing file exited 1

  verdict        PASS
```

Every descriptive field is honest.  The verdict is still wrong, and the truth
probe proves it: the readable `DANGEROUS` file exits 0.  Two visible facts should
force refusal — the exclusion contains the subject of the claim, and the
negative control died in `Path.read_text` before any content oracle.  The form
states neither rule.  `authored YES` is also only a field: section 5 requires an
independent verifier for a measured claim, but the form has no verifier field or
signature and does not map this answer to `REFUSED`.

The missing control fields are:

```text
control mutation       SAFE content -> DANGEROUS content; nothing else
expected observation   content oracle returns REFUSED
observed observation   process exits non-zero at content oracle
failure signature      named event/message/branch proving that locus
```

A non-zero process status alone is not that proof.

## Counter-example 2 — an existing checker and an unmeasured population

The repository's citation checker was run against a synthetic root:

```text
valid target.md line 1           citations 1, hard 0, exit 0
missing missing.md line 1        citations 1, hard 1, exit 1
missing missing.MD line 1        citations 0, hard 0, exit 0
```

The output is `/tmp/build78-citation/evidence.log`, SHA-256
`59b1e816a5472aad8c166f2cbad8f8193f4216b49d88492c5183f7cbaac71cef`.
The lower-case negative control is genuine.  It cannot support the broader
claim that missing Markdown targets are rejected, because the recognizer never
enters the uppercase population.  Again, the form permits both an `EXCLUDED`
line naming unmeasured extension spellings and a `PASS` claiming the whole
population.  Population counts and partitions are not merely useful prose:
the claim must be a subset of the exercised population, or the verdict is
`REFUSED`.

## `NOT ESTABLISHED` makes `could it fail` non-gating

As written, yes.  `NOT ESTABLISHED` is a good value to preserve ignorance, but
there is no consequence attached to it.  This passes the syntax:

```text
could it fail  NOT ESTABLISHED
verdict        PASS
```

For a claim presented as evidence, `NOT ESTABLISHED` must force `REFUSED`.
There can be a separate `SMOKE` outcome for a useful run without a control; it
must not share `PASS`.  `UNKNOWN` in `sha`, `built from`, `command`, `exit
status`, or evidence provenance should likewise force `REFUSED` rather than
merely fill a field.

## The SHA does not identify the artefact that ran

`sha` identifies a repository state.  It does not prove that a container,
installed editable package, copied tree, cached image, or already-running
process came from that state.  `built from COMMIT` is an assertion of the same
fact, not an independent binding.

Replace the pair with an artefact identity that is measured at the execution
boundary, for example:

```text
source sha       <full sha>
artefact         image digest | installed wheel digest | tree digest
reported sha     value emitted/read from the running subject, where available
```

A source SHA plus an unrelated old image can currently receive `PASS` with no
field visibly false to someone who inspected only the checkout.

## Length and fields to cut

The eleven-line form is not too long.  The 120 lines explaining it are.  I
would cut no semantic evidence field merely to shorten the form.  I would make
three structural reductions:

1. Merge `sha` and `built from` into the stronger source-and-artefact identity
   above.  Cost if `built from` is simply deleted: working-tree smoke becomes
   indistinguishable from reproducible evidence.
2. Move `run by / authored` into a mandatory adjacent `VERIFIED BY` signature.
   Cost if it is merely deleted: self-signing becomes invisible.  The move is
   valid only if the signature cannot be detached from the run record.
3. Permit `host: NOT MATERIAL — <reason>` for hermetic checks instead of making
   every author explain `local`.  Cost if `host` is deleted: environment- and
   performance-dependent runs become incomparable again.

The worked narrative should move to a method/history document after one compact
PASS and one compact REFUSED example are added.  Removing the worked example
today costs the only demonstration of how fields affect a verdict; replacing it
with two small examples improves that rather than weakening it.

`command`, unpiped `exit status`, evidence identity, `EXCLUDED`, the strengthened
control, claim and verdict all remain.  Those are the minimum causal record.

## Where the six proposed additions belong

| addition | disposition |
|---|---|
| never destroy what this run did not create | Conditional sign-off block for live/destructive runs: created identity, destroyed identity, refusal control. Section 6 prose alone cannot be filled or checked. |
| compare like with like | Conditional comparison block: both source SHAs/artefacts, same host/session/method, order or interleave. Section 6 prose is not enough. |
| state the population | In this form. Strengthen `EXCLUDED` with exercised count/partition and require the claim to be contained by it. |
| preserve falsified predictions | Method/build-results document, with a `prediction` field required only for experiments and comparisons. Requiring it for unit checks is noise. |
| verify the representative path | In this form: name the subject path/contract and require evidence that the command crosses it. It is not equivalent to listing nearby tests. |
| a correction retires the prior claim | Method document, not each run. A replacement sign-off must name the superseded sign-off and state that its verdict is dead. |

## Real-run score — Build 55

The surviving record is commit
`5b0efb3aebf80637dda7f8c8d16e541782a51236`.  It says the negative control
produced plumbing 24/1, `NOT accepted`, exit 1; unmodified main produced 25/0,
19/0, exit 0; exactly one of twelve audited scenario scripts had the defect.
The implementation commit is
`6370b2eb8ddc0793fa5eb2934b92d2af48e0bf20`.

Scoring only what the durable record can support:

```text
TEST SIGN-OFF

  claim          a plumbing failure propagates to accept.sh exit 1
  sha            UNKNOWN — 6370b2e is the implementation, not a recorded run SHA
  built from     WORKING TREE for the forced mismatch; exact tree UNKNOWN
  host           UNKNOWN — the build required lab, but the surviving result does
                 not bind the output to a host
  run by         bus         authored the change? YES

  command        UNKNOWN — no exact invocation survives
  exit status    1 — recorded in the merge commit, but not in retained raw evidence
  evidence       UNKNOWN — the lab-local log path and hash do not survive

  EXCLUDED       exact population UNKNOWN; the failing run stopped at plumbing,
                 so it did not establish simulator, client, or throughput behavior
  could it fail  yes — the forced actual != expected produced 24/1 and exit 1

  verdict        REFUSED as a reproducible sign-off; strong historical evidence
```

Fields that cannot be filled are the run SHA, exact working-tree identity, host
binding, exact command, retained evidence path/hash, and complete excluded
population.  Build 55 was correctly accepted at the time because the operator
saw the live raw output and independently repeated the result.  The repository
record supports the historical conclusion, but it cannot reconstruct a current
form that another reader could reproduce.

That distinction is the form's purpose: not to rewrite Build 55 as a failure,
but to show which evidence did not survive it.
