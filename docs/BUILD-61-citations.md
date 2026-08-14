# Build 61 — the docs cite 287 places; nothing checks that they exist

> **Base on `main`.** Branch `bus/build-61-citations`, push to origin.
> Owner: `bus`. ⚠ `api` is on build 60 and owns `API.md` — do not edit it; report
> what the checker finds there and let them fix it.

## 1. Why now

`main` is the whole project — one branch, 361 green, ten builds merged in two
days that **renamed every module and moved files**. The docs were carried along
by a codemod for the code paths, and by hand for everything else.

**Measured on `main` today:**

| | |
|---|---|
| unique `path.py:line` citations across `docs/` | **287** |
| live design docs citing **paths that no longer exist** | `GLOSSARY:152–153`, `DESIGN-layers:170–171, 293` |
| `send_refused` in `CONTRACTS.md` | ⚠ **zero** — build 54 added a sixth custody record |

⚠ **`GLOSSARY:152` currently says the port sends "(`adapter/cli.py` today)".**
That file does not exist. The word "today" is doing the damage — it is a claim
about the present that is false.

## 2. Build the checker first

`tools/check_citations.py`, run over `docs/`:

1. extract every `path:line` reference
2. **the path must exist**
3. **the line must exist** in that file
4. ⚠ **the line should be plausible** — if the citation is next to a quoted
   symbol, that symbol should appear at or near that line. Report near-misses
   separately from hard failures; a citation off by three lines is worth knowing
   and is not the same as one pointing at a deleted file

**Exit non-zero on hard failures.** ⚠ Per
[`BUILD-CONVENTION`](BUILD-CONVENTION.md) §1, **prove it can fail**: point a
citation at a deleted file and at a line past end-of-file, and show both caught.

⚠ **Print the count of citations checked.** A checker that finds nothing because
its regex matched nothing is this project's favourite failure mode — four
instances in two days.

## 3. Then fix, in this order

1. **Hard failures** — dead paths, out-of-range lines
2. **`CONTRACTS.md`**: `send_refused` alongside the five. ⚠ State whether it is
   a **sixth custody record** or a **different kind of record** — it is emitted
   for an envelope that was never enqueued, so the five-record set does not and
   should not apply to it. That distinction is the interesting part
3. **Near-misses** — report the count; fix only where the citation misleads

⚠ **Do not touch `docs/API.md`, `GLOSSARY.md` or `DESIGN-layers.md`.** `api` owns
the first, `architect` the other two. Report their findings.

## 4. ⚠ The codemod's exclusion list is now stale, and this is the subtle part

`tools/rename_vocabulary.py` excludes six documents because they *describe* the
rename and had to read correctly in both vocabularies. **The transition is over,
so the exclusion has flipped from protective to harmful**: those documents now
freely contain old words that nothing will ever correct.

⚠ **Each old word in those six is now one of two things**, and only a human can
say which:

- **historical** — "`port` — was `adapter`" is correct and must stay
- **stale** — "the port sends (`adapter/cli.py` today)" is simply wrong

**Report the count of each per document. Do not mass-edit them.** Recommend
whether the codemod and its exclusion list should now be deleted — `BUILD-56` §5
said it stays one release as the record of the transition.

## 5. Done when

- `tools/check_citations.py` exists, prints the count checked, exits non-zero on
  hard failures, and **has been shown to fail**
- zero hard failures in the docs `bus` owns; findings reported for the rest
- `CONTRACTS.md` covers `send_refused` with the enqueued/never-enqueued
  distinction stated
- `python3 -m pytest -q` green (361 at the time of writing)

⚠ No lab needed. This build touches no runtime code.

## 6. Reporting

`jira done`, then message `architect` with: citations checked, hard failures
fixed, near-misses found, the historical-vs-stale counts for the six excluded
documents, and your recommendation on deleting the codemod.
