# Build 105 — the monitor stops saying things that are false

**Base: `main` at `b06992d`.** Branch from main, push to origin.

Two claims the watchdog surface makes today that are not true. ⚠ **Neither is a
missing feature. Both are false statements**, which is why they come before
anything that adds capability.

## 1. A recovered credential is never retracted

`src/flock/watchdog/service.py:318` — when a credential goes healthy:

```python
else:
    self.r.hdel(alerted_key, field)
    continue
```

**It clears its own dedupe marker and emits nothing.** The alert stream still
carries the stale `absent`, and nothing supersedes it. ⚠ **The watchdog knows the
state changed and stays silent** — the same shape as the swallowed `_kick` that
build 95 fixed.

**Measured**: `status=absent` raised at `01:00:42Z`, login completed at `01:07Z`,
nothing retracted for an hour, and the console correctly rendered a fact that had
been false the whole time.

⚠ **`BUILD-38-durable` §2 offers two routes.** §1's clearable alerts do not exist,
so **emit `status=present` and let readers take the latest per `account`+`cli`**
is the buildable one — but **say which you chose and why in `LLD-watchdog`**, per
that spec.

⚠⚠ **This was only ever tested FIRING. Test the transition back.** A guard nobody
has watched stop is half-built, and this row exists because of exactly that.

## 2. ⚠ `CONTRACTS` asserts something false about agy — and the correction must
not overshoot

Build 88 concluded agy *"records no token counts anywhere"*. **That conclusion
came from an incomplete capture**: six named paths were taken and
`~/.gemini/antigravity-cli/brain/` — where per-conversation transcripts live —
was never looked at. The directory was visible in the listing at the time.

**Correct three places**: the agy paragraph in `CONTRACTS.md`,
`BUILD-88-results` §3, and the `not measurable (agy)` label in `office status`
and `office usage`.

⚠ **Say only what is known, in both directions:**

- agy writes a per-conversation transcript under
  `brain/<id>/.system_generated/logs/`
- **h-flock does not collect it** — that is our limitation, not agy's
- ⚠ **whether those transcripts carry token counts is UNVERIFIED.** Nobody has
  read one. **Do not assert that they do.**

**The label should say `not collected`, not `not measurable`.** One describes us;
the other makes a claim about agy we no longer have evidence for. ⚠ **The
original error was a claim broader than its evidence — do not replace it with a
different one.**

## Done means

Pushed. Tests green. `TEST-SIGNOFF`, verifier assigned by me. ⚠ **The retraction
is behavioural** — a test that executes the absent→present transition and
asserts the emission. ⚠ **The doc corrections need tests asserting the sentence**,
per the rule build 93 produced. ⚠ **Merged-tree check required**: `CONTRACTS.md`
is a living document.
