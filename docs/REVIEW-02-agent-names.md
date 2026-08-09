# Review 02 — does your module survive the new default names?

> The default office is now `architect`, `sme-2`, `sme-3` instead of
> `alice`, `bob`, `carol`, and every doc example is named for a job.
>
> **Pull `main` first.** Report findings; fix only files your lane owns.

## 1. The one genuinely new thing: hyphens and digits

Every agent name this project has ever run with was a single lowercase word.
**`sme-2` is the first with a hyphen and a digit**, and it is a valid segment —
`^[a-z0-9][a-z0-9-]{0,62}$` has always allowed it. Nothing has exercised it.

⚠ **This is where a break will be, if there is one.** Look for anywhere a name
is split, matched, interpolated or pattern-matched in your module:

- key building and parsing — a name inside `pod:…:agent:<name>:…`
- tmux targets — `hq:sme-2`, and window names generally
- regexes and globs over agent names or keys, especially `KEYS` patterns
- argument parsing — a name that could be read as a flag or a range
- anything that treats `-` as a separator
- id-prefix matching on the board, where a name and an id sit near each other

⚠ **A name is not a path component alone.** `sme-2` appears in
`/workdir/sme-2`, in Redis keys, in tmux targets and in URLs. Check the ones your
module actually constructs rather than assuming.

## 2. Hardcoded names

`src/` and `tests/` still contain the old names in places. **Tests were left
alone deliberately** — renaming fixtures is churn with no benefit and some risk.
What matters is anything that would only work for a *particular* name.

Report, per lane:

- any place your module assumes a specific agent name
- any test that would pass for `alice` and fail for `sme-2`

⚠ **`plumbing-check.sh` was exactly this** — it hardcoded two names and would
have broken against every office but the one it was written for. It now reads
them off the roster. If your module has the same shape anywhere, that is the
finding.

## 3. Your docs after the rename

133 replacements went through the docs mechanically. Read your own files and
check none of them now say something silly or wrong — a sentence that read well
about `alice` and reads oddly about `backend`, or a renamed example that no
longer matches the code beside it.

⚠ **`VERIFIED-*`, `BUILD-*`, `AUDIT-*` and `REVIEW-*` were deliberately not
renamed.** They record runs that happened. If one of them mentions `alice`, that
is correct and must stay.

## 4. Verifying for real

The lab tenant is running the new defaults — `architect`, `sme-2`, `sme-3` — and
`container/plumbing-check.sh` passes 25/25 against it three runs in a row. That
covers the paths the check exercises, which is not the same as covering yours.

⚠ **A unit test proves less than usual here.** The build 17 drift passed every
unit test on both sides. If your module builds a key, a target or a path from a
name, exercise it with `sme-2` specifically.

## 5. Reporting

`jira done`, then message `architect` with: what you checked, what you fixed, and
anything you found that assumes a name's shape. **"Checked and sound" is a
result** — say what you checked, not only what broke.
