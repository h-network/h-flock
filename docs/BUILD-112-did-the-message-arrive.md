# Build 112 — did the message actually arrive?

**Lane: `acceptance`. Base: `main` at `58810e8`.**
⚠ **Host: the lab. This is a CORRECTNESS question, not a performance one** — a
swallowed Enter is swallowed at any speed. Build 111 measured throughput on
h-oracle; this measures whether the message got there.

## What is missing, and why it matters

Build 111 reported `PASTE_ENTER_DELAY=0` at **15 ms and 363/s** against 507 ms
and 19.56/s at the default. ⚠ **Its arrival column reads `custody-opened`, and
`opened` does not prove arrival.**

`src/flock/tmux/ops.py:455-468` is `load-buffer`, `paste-buffer`, sleep,
`send-keys Enter`, return. **Nothing reads the pane.** So `opened` means tmux
accepted four commands.

⚠⚠ **BUILD-111's spec required a marker per envelope counted at the destination.
It was never delivered, `tmux` said so in its refusal, and the architect accepted
a wording correction instead of the measurement.** That is the gap this build
closes.

## ⚠⚠ THE REQUIREMENT THAT DECIDES WHETHER THIS RUN IS WORTH ANYTHING

**Build 111 ran against a PLAIN SHELL. A plain shell has no input box.**

`ENTER_DELAY` exists for **CLI input boxes** — Claude Code's Ink, codex, agy —
where `docs/LLD-port-tmux.md:197-208` documents the Enter being coalesced into
the paste and the message sitting unsubmitted. **A plain shell cannot exhibit
that failure at all**, so build 111's zero-delay result says nothing about it.

⚠ **Deliver into a REAL CLI pane.** An unauthenticated agent is fine — an agent
showing *"Not logged in"* still runs the Ink UI and still has an input box, so
this needs no credentials.

**If you deliver into a plain shell again, this build has measured nothing.**

## Method

Per envelope, a **unique marker** in the body. After delivery, **read the pane**
(`capture-pane`) and count markers that actually appear **as submitted input**,
not merely as pasted text sitting on the prompt line. ⚠ **Those two are the
whole distinction** — pasted-but-unsubmitted is exactly the documented failure.

Run both configurations, **interleaved rather than in blocks**, and report per
configuration:

- envelopes sent
- `opened` records emitted
- **markers actually submitted in the pane**

⚠ **The gap between the second and third columns is the deliverable.**

## What a result looks like

⚠ **`delay=0` losing submissions is a FINDING, not a failure of the run** — it
would confirm the mitigation is load-bearing and settle whether that number may
ever appear in a README.

⚠ **`delay=0` losing nothing against a real CLI would be a genuine surprise**,
and would need saying carefully: which CLI, which version, how many envelopes.
**It would not license changing `ENTER_DELAY`** — one clean run does not overturn
a mitigation raised deliberately in build 14 after ours was an order of magnitude
out against measurements elsewhere.

## Out of scope

⚠ **Do not change `ENTER_DELAY`. Do not touch `README.md`** — it is getting a
capability rewrite later, not a number patch. **Do not re-measure throughput**;
that is done and it is not your host.

## Report

Per `BUILD-83`. ⚠ **Name which CLI you delivered into and whether it had an input
box** — that single fact decides whether the numbers mean anything. Hash the log
and push the evidence.
