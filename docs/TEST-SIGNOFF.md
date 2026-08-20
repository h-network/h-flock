# Test sign-off

⚠ **A test result is a claim, and this is the shape it must take to be one.**
Every field below exists because a run in this repository was reported as
evidence when it was not. The build number after each is the run that earned it.

**Fill it, or say the field is UNKNOWN.** A missing field is not a pass.

---

## The form

```
TEST SIGN-OFF

  claim          what this run establishes, in one line
  sha            <full sha>                  ⚠ the commit, not "main", not "latest"
  built from     COMMIT | WORKING TREE       ⚠ see §1
  host           lab 172.16.0.14 | h-oracle | local   + why that host
  run by         <lane>       authored the change?  YES | NO

  command        the exact command
  exit status    <n>          read UNPIPED — see §2
  evidence       <path>       + sha256 if it will be torn down

  EXCLUDED       the paths and populations this run did NOT exercise   ⚠ §3
  could it fail  the negative control that was run, or NOT ESTABLISHED ⚠ §4

  verdict        PASS | FAIL | REFUSED
```

---

## 1. `built from` — the field that invalidates most of the rest

⚠ **A container built from an uncommitted working tree verifies nothing that
anyone else can reproduce.** It is a useful smoke test and it is not evidence.

**2026-08-18**: a watchdog change was verified live on h-oracle by `tar`-ing a
working tree into a clone and rebuilding. The behaviour was correct. The commit
was on the wrong branch and `main` never moved — so the "verified live" claim
described code that was nowhere in the repository.

**`WORKING TREE` is a legal answer.** It downgrades the verdict to
*smoke-tested*, and the claim must say so.

## 2. `exit status` — read it unpiped

⚠ **`cmd | tail` reports `tail`'s status.**

```bash
cmd > /tmp/out 2>&1; echo "exit=$?"; tail -5 /tmp/out
```

**BUILD 55**: `accept.sh` counted plumbing **24 failures** and returned green,
because the pipeline reported the consumer's status. Fixed with `PIPESTATUS[0]`
plus a forced `actual != expected` negative control.

**2026-08-18**: a hard citation failure was pushed because
`check_citations.py 2>&1 | tail -2 && git push` let `tail`'s zero through.

`set -o pipefail` is the minimum; reading the status of the thing you ran is the
rule.

## 3. `EXCLUDED` — name paths and populations, not commands

⚠ **"All tests pass" is not a statement about the system.** It is a statement
about the tests that ran.

**BUILD 51**: a 100×20 API bench was green and covered adapter delivery. It did
not cover tmux paste or control. Acceptance had to be rerun, because only
`accept.sh` proved a kicked tmux delivery reached a pane.

**BUILD 29/33**: `clients/telegram/bot.py` had `def enrol():` missing `self`.
Pytest was green on mocks; it excluded ever instantiating the client. **The live
bot crashed on call #1.**

So: *"excluded `accept.sh`, the tmux paste path, and any container build"* —
**not** *"ran pytest"*.

## 4. `could it fail` — a pass is evidence only if failure was reachable

⚠ **Ask what result would have appeared had the property been false.** If the
answer is "the same one", the run establishes nothing.

**BUILD 53**: the L2-only gate was proven by pointing the switch at
`l3.destination` and watching it exit 1.

**BUILD 62**: a negative control **passed for the wrong reason** — it withheld
the launcher rather than exercising the condition under test.

**2026-08-19**: a free-port probe piped `ss` to `grep`. Where `ss` is absent the
pipeline returns nothing, every port reads free, and **both the suggestion and
the collision refusal silently stop working.** It was replaced with a `bind()`
and proven both ways.

**`NOT ESTABLISHED` is a legal answer** and is far better than a claimed control
that was never induced.

## 5. `run by` — the author's own green is the weakest evidence there is

⚠ Not a prohibition. A field.

**BUILD 77**: three commits authored, implemented and self-reviewed by
`architect` shipped two defects — a `setup.sh` that produced an API-dead tenant,
and `WATCHDOG_ENABLED=0` silently killing all presence and activity telemetry.
Both were found by `api` on first independent read.

**Anyone may attack; only an independent reader signs.** Where the change is
load-bearing — contracts, wire or custody, destructive paths, harnesses, or a
measured claim — the verifier of record must not be the author.

## 6. Two things that void a sign-off regardless of its fields

⚠ **A run that destroyed something it did not create.** BUILD 59 killed the live
office because the compose project was derived from the tenant name and teardown
ran `down -v`. Record the identity this run created; tear down only that.

⚠ **A comparison across hosts, sessions or methods.** BUILD 68 would have
reported a 21% regression by comparing against a historical figure; paired on
one host it was −2.11%. Identical scripts measure **6.5/s on the lab and 853/s
on h-oracle** — see `BUILD-CONVENTION` §3.0.

---

## Worked example — a sign-off that fails its own form

```
  claim          the watchdog observers survive WATCHDOG_ENABLED=0
  sha            f33885a
  built from     COMMIT
  host           lab 172.16.0.14        correctness, not a throughput claim
  run by         architect              authored the change?  YES   ⚠ §5

  command        docker compose -p h-flock-b77 … up -d --build
  exit status    0                      read unpiped
  evidence       /tmp/b77-build.log on the lab            ⚠ no sha256, torn down

  EXCLUDED       accept.sh, plumbing-check.sh, every scenario that enrols over
                 HTTP, the tmux paste path, and any second tenant
  could it fail  YES — the same tenant with the pre-fix entrypoint does not
                 start flock.watchdog at all                ⚠ NOT ACTUALLY RUN

  verdict        PASS  ← ⚠ should be REFUSED
```

⚠ **Two fields sink it.** The author signed their own change, and the negative
control was asserted rather than induced — the pre-fix comparison was never run,
so nothing distinguishes "the fix works" from "the observers were always going
to write those keys". **The evidence was also torn down without a checksum.**

That run is in this repository and was reported as verification.
