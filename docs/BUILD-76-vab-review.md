# Build 76 — review our fabric against h-vab's design

> **Base on `main`.** Branch `bus/build-76-vab-review`, push to origin.
> Owner: `bus`. ⚠ **ANALYSIS ONLY — no product code, no renames, no refactors.**
> Deliverable is one document.

## 1. What to read, in this order

1. ⚠ **`docs/BUILD-46-vabtrial.md` and `docs/BUILD-46-bus-results.md` FIRST.**
   **You already ran this trial.** Build 46 put one path on the h-vab shape and
   reported eight concrete conflicts. Do not re-derive them — start from them and
   say which still hold after builds 47–75.
   ⚠ Note `BUILD-46-vabtrial.md` was damaged by the build-56 rename and repaired
   on 2026-08-15; `h-vab`, `adapter` and `router` in it are **h-vab's** vocabulary,
   not ours.
2. `git@github.com:h-network/h-vab.git`, branch `naming/vocabulary` —
   **`docs/FLOW.md`** then **`docs/NAMING.md`**. ⚠ **Nothing there is built.** It
   is a design with no implementation, which is the reverse of how we arrived.

## 2. Scope — the fabric only

**In:** `src/flock/bus/` and `src/flock/switch/service.py` — 1,029 lines.

**Out:** `tmux`, `tmuxhost`, `session`, `office`, `control`, `api`, `port`. h-vab
says nothing about panes, CLIs or boards, and their names were never the problem.

⚠ **Also out: `switch/activity.py`, `presence.py`, `verification.py`,
`windowlog.py`, `retention.py`.** They live under `switch/` but they are not the
fabric — see §3.

## 3. What we found on 2026-08-15 that already maps

Confirm, correct or reject each. **Where you disagree, say so** — these are my
readings from one pass, not findings.

| ours | h-vab |
|---|---|
| five observers run **inline on the forwarding thread**, one `try` around all five | **§8** — observer *"reads state ╳ never writes ╳ never in the forwarding path"* |
| a reach set combining forwarding + ACL in one lookup | **§9** `select_egress(source, destination)` → hit+permitted, or **dead-letter denied** |
| the kick is a **sole-path** doorbell; build 73 produced a frame in ingress no kick will ever collect | *"Why ⑪ cannot be the only path to the drain"* — level-triggered condition, doorbell as optimisation |
| `send_refused` vs `dead_lettered` | **reject vs dead-letter by DECIDABILITY**, not severity |
| the switch reads the whole 256-byte header, including `ttl`/`hops` it decrements | **§4 frozen read-set** — the switch reads `source`+`destination` only and *therefore cannot* enforce the hop limit; that belongs to the router |

## 4. The questions to answer

1. **Where do we already agree**, in behaviour rather than vocabulary?
2. **Where do we diverge, and is each divergence deliberate or accidental?**
   ⚠ Build 73's `ttl`/`hops` in the L2 header is the clearest candidate. I
   specified it. Say whether h-vab's tighter read-set is better and why.
3. **What does h-vab solve that we have not?** The terminal strand is the one I
   can see. Are there others?
4. **What do we have that h-vab does not account for?** Build 46 found eight.
   Which survive? ⚠ **This half matters as much as the first** — a design that
   cannot express something we need is a finding about h-vab.
5. **Which of our 67 measured comments** in those 1,029 lines encode something
   h-vab's design does not prevent? Those are the ones that must survive any
   rebuild, and re-deriving them costs what they cost the first time.

## 5. What NOT to do

- ⚠ **No code.** Not a spike, not a branch of the fabric, not a rename.
- ⚠ **Do not recommend adopting or rejecting h-vab.** That decision is Halil's.
  Give him the comparison he needs to make it.
- ⚠ **Do not treat h-vab as authoritative because it is written down.** It has no
  implementation and no measurements. We have 388 tests, proven conservation and
  a v4 wire verified byte-identical against real model output. **Where our
  measured behaviour contradicts their design, that is evidence, not error.**

## 6. Done when

`docs/BUILD-76-vab-review.md` exists on your branch and answers §4, with
`file:line` for our side and section references for theirs. `python3
tools/check_citations.py` clean.

`jira done`, then message `architect` with the five answers in a line each.
