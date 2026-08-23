# Build 93 — document the surface three builds actually shipped

**Lane: `api`. Base: `main` at `0d8379a`.** Branch from main, push to origin.

Builds 87, 88 and 91 changed what an operator and an agent see. The reference
documents still describe what they saw yesterday. ⚠ **This is a narrow build with
a verifiable definition of done, not a sweep** — every claim below is checkable
against code, and if a claim is not checkable, leave the document alone and say
why.

## 1. `office send`'s contract is documented nowhere current

`docs/API.md:12` still shows `office send -a telegram hello`. It happens to work
— one word — but it teaches a form that fails the moment a second word appears.

**The shipped contract:**

```
office send -a NAME "one quoted argument"
office send -a NAME --stdin          # body on stdin
office send -a NAME --file PATH      # body from a file
office send --agent=NAME "…"         # the equals form works
office send -a NAME -- --leading-dash-body
```

The acknowledgement is `sent to NAME: N bytes (STREAM_ID)`, and **the byte count
is the point** — an agent that meant to send 4 kB and sees 8 bytes knows the body
was lost. Say so where the form is taught.

⚠ **`broadcast` deliberately kept `argparse.REMAINDER`, so it does NOT follow
this.** ⚠ **Do not "fix" that here and do not paper over it** — it is a decision
on `TODO.md`. Where both are documented, **state the difference plainly** rather
than implying one convention.

## 2. `office usage` and `office status` gained output nobody documented

Verify each against the code before writing it — `src/flock/office/cli.py` and
`src/flock/watchdog/activity.py`:

- codex rows carry a **rate-limit column** (`used_percent`, `plan_type`)
- an agy agent reads **`not measurable (agy)`** in `status`, and
  `model=not measurable` with `-` for every count in `usage`
- `office usage --json` carries **`"measurable": false`** on rows that cannot be
  measured, and claude rows do not have the key
- codex rows price against a model resolved from `turn_context`, so they no
  longer read `unpriced`

⚠ **`rate_limits` has never run against a live codex agent** — it passes against
`tests/fixtures/codex-session-captured.jsonl` only, and the 2026-08-23 acceptance
tenant had no codex agent (`BUILD-90-results`). **Document it as shipped and say
that it is unproven live.** A reference document that quietly implies live
verification is the same defect as a green run that covered nothing.

## 3. Control records exist and are not in the contract

`docs/CONTRACTS.md` lists record events and does not include
`{start,stop,pause,resume}_agent_{accepted,incomplete,failed}`.

⚠ **`_accepted` does NOT mean the hire worked.** It means every desired-state
write was acknowledged; actual state is applied asynchronously by
`tmuxhost.reconcile_once`. ⚠ **Write that limit into the contract**, because the
obvious reading of "accepted" is the wrong one and a row on `TODO.md` exists for
the half that is missing.

⚠ **`bus` owns `CONTRACTS.md:318-322` in build 92** — the attempt-record
paragraph. **Coordinate: add your control records, do not touch that paragraph.**
Same file, two builds, so say in your report which lines you took.

## Out of scope, deliberately

Seven other documents mention `office usage` or `office status`. ⚠ **Do not open
them.** Most will be fine, and a sweep that edits by feel is how a previous
auditor on this project cited files that did not exist. If you believe one is
wrong, **name it in your report** and it becomes a drift review, not this build.

## Done means

Pushed. Tests green — `tests/test_citations.py` matters most here. `TEST-SIGNOFF`
filled in, **`VERIFIED BY` is not you** and I assign the verifier. ⚠ **Bind each
gate to the FINAL commit** and prove the number reproduces there.
