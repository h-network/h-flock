# Review 01 — the architecture document

> [`HLD.md`](HLD.md) is new and has never been checked against the code. It is
> the document a newcomer reads first, so an error in it propagates into every
> later assumption.
>
> **Pull `main` first.** No branch and no commit — see §2.

## 1. Review only. Do not edit

Three lanes editing one file is a conflict, and this file is short enough that I
can apply every finding myself. **Read it, check it, report.**

## 2. What to check

Against the code you own, not against your memory of writing it.

**Is it true?** Every claim about your module. The section that matters most to
each of you:

| lane | sections | |
|---|---|---|
| `bus` | §1, §2, §5, §6, §10 | the switch, VABs, the envelope's path, kinds, the invariants |
| `tmux` | §3, §4, §6, §9 | the parts, why adapters are kicked, openers, the tenant |
| `api` | §3, §6, §7, §8 | the two doors, kinds an app sees, pulled-not-pushed |

Read the whole thing regardless — the point is a newcomer's view, and you are the
closest thing to one for a module you did not build.

**Four failure classes, in order of how much damage they do:**

1. **Anything unverifiable.** A number, a duration, a count, a "we found that…".
   ⚠ A review of this file already caught an invented timeframe — *"promised an
   atomic `LMOVE` for a year"* in a repository three days old. If a claim has a
   quantity in it and you cannot check the quantity, say so.
2. **Cross-references that do not resolve.** The same review caught §2 citing the
   LLD's invariant numbering while presenting the HLD's own. Follow every `§`,
   every file link, every "see below".
3. **Claims that are true of one participant and stated of all.** "Agents never
   see clients" was wrong for exactly this reason. Watch every *always*, *never*,
   *only*, *nothing else*.
4. **Missing pieces.** `PauseAgent`/`ResumeAgent` were in the README and absent
   here until the same review. What does your module do that this file does not
   mention at all?

## 3. What not to report

Wording you would have phrased differently, or a section you would have ordered
another way. This is a correctness pass. If something reads badly *and* is
misleading, that is finding class 3 and worth reporting; if it merely reads
badly, leave it.

⚠ **"I checked §7 and it is accurate" is a result**, and a useful one. Say what
you checked and found sound, not only what you found broken — otherwise I cannot
tell a reviewed section from a skipped one.

## 4. Reporting

`jira done`, then message `architect` with, per finding: **where**, **what is
wrong**, **what is actually true**, and how you verified it. Plus the list of
sections you checked and found correct.
