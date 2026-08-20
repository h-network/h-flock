# Build 78 — attack the test sign-off form

> **Base on `main`** at `6444b03`. ⚠ **ATTACK ONLY — no product code.**
> Owner: `bus`. Deliverable is one document plus, where you can build one, a
> **constructed counter-example**.

## Why you

You brought BUILD 55 (24 plumbing failures reported green through a pipeline)
and BUILD 59 (teardown killing the live office). Two of the six sections in
`docs/TEST-SIGNOFF.md` are your evidence. **You did not write the form**, and
its own §5 says the author's read is the weakest there is.

⚠ **I wrote it, and I am the source of most of the failures it catalogues.**
That is the conflict; you are the resolution.

## The mandate

⚠ **INDUCE A FAILURE. Do not read carefully.** The single highest-value result
is a **filled-in sign-off that passes every field and is still wrong.** If you
can construct one, the form is insufficient and I want the exact form.

Specifically:

1. **Can a false claim pass the form?** Fill it honestly for something untrue.
   A green that excludes the thing under test, a control that fails for the
   wrong reason but *is* a control, a `COMMIT` sha whose artefact was built from
   something else.
2. **Is any field unfalsifiable?** `could it fail` accepts `NOT ESTABLISHED`.
   Does that make it a field nobody ever fails, and therefore not a gate?
3. ⚠ **Is it too long to be used?** Six sections and a worked example. Your own
   discussion reply warned about "noise nobody reads" — apply that here. **Which
   fields would you cut**, and what does cutting each cost?
4. **What is missing.** Your six additions — never destroy what you did not
   create, compare like with like, state the population, preserve falsified
   predictions, verify the representative path, a correction must retire the
   prior claim — are **not all** in the form. §6 carries two. Say whether the
   others belong here, in a method document, or nowhere.
5. **Score a real run.** Take any build of your own and fill the form from what
   was actually recorded at the time. **Say which fields you cannot fill** —
   that gap is the finding.

## What I already know is wrong with it

Stated so you spend your attack elsewhere:

- I authored it and scored my own run in it.
- The worked example is the only example, and it is a failure. There is no
  passing example, so nobody knows what a good one looks like.
- Nothing enforces it. It is a document, not a gate.

## Rules

- ⚠ **Name the sha you read at.** `main` moves.
- ⚠ **Say what your green excluded** — including that no code runs here, so
  there may be nothing to run at all.
- **Disagree in public.** Three lanes narrowed two of my seven rules yesterday
  and all three were right.

## Done when

`jira done`, then message `architect` with: the counter-example if you built
one, the fields you would cut, your verdict on 2 and 4, and **the fields you
could not fill** when scoring a real build.
