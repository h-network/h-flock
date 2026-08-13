# Build 44 — the docs against each other

> The 50-row audit checked **docs against code**. This checks **docs against
> docs**: two places, both written by us, both plausible, saying different things.
>
> **Base on `main`.** Branch `<lane>/build-44-consistency`, push to origin.

## 1. The worked example, so nobody has to guess what a finding looks like

`LLD-bus-and-router` describes cross-tenant routing twice, differently:

- **§7** — *"Not a separate component — a branch in the router. When a
  `recipient` does not resolve inside the local tenant, look it up in a registry
  of enrolled tenants and write the envelope to that tenant's Redis."*
- **§3.2 and line 169** — `gateway` is a reserved **VAB**, a participant; `pod`
  is *"a gateway, when routing between tenants"*.

A router that holds remote tenants' Redis addresses contradicts the same
document's own principle — *"keeping it there is what stops topology knowledge
spreading"* — and has one tenant writing another's store. A participant
addressed by name does not. **Both are written down; only one can be built.**

That is the shape: not a typo, not staleness. Two designs coexisting because
nobody read them side by side.

## 2. What to check, in this order

1. **Your document against itself.** The same rule stated twice with different
   content. Long documents accumulate these.
2. **Your document against `HLD.md`.** The HLD states invariants; an LLD that
   quietly relaxes one is the dangerous case.
3. **Your document against `CONTRACTS.md`.** Anything two modules depend on.
4. **Your document against the other LLDs where they touch** — the seams:
   adapter↔router, api↔session, container↔everything.

## 3. Ownership

| lane | documents |
|---|---|
| `bus` | `LLD-bus-and-router.md`, `CONTRACTS.md` |
| `api` | `LLD-api.md`, `LLD-session.md`, `API.md` |
| `tmux` | `LLD-tmux-host.md`, `LLD-adapter-tmux.md`, `LLD-container.md` |
| `architect` | `HLD.md`, `TODO.md`, `README.md` |

⚠ **Do not edit a document you do not own.** Report the line and let the owner
fix it — that rule caught three of my own false claims last week.

## 4. ⚠ The rule that matters most

**A contradiction about *description* — fix it.** If two places describe what the
code does and one is wrong, the code decides, and you correct the wrong one with
the line numbers in your report.

**A contradiction about *design* — do NOT fix it. Report it and stop.** Where two
documents describe different intended futures, picking one is an architecture
decision, and it is mine and the operator's to make, not a lane's. The gateway
fork is exactly this: choosing "branch in the router" or "participant with a VAB"
sets what gets built next year.

⚠ **Guessing here is worse than leaving it.** A lane that quietly resolves a
design fork enshrines a decision nobody made, and it will be discovered later as
though it had always been intended.

## 5. What is NOT a finding

- wording differences that mean the same thing
- an LLD giving more detail than the HLD — that is the point of an LLD
- something already marked deferred, open, or parked, which is a statement about
  the future rather than a claim about now

⚠ **"I read it and found no contradictions" is a valid and useful result.** Say
which documents you read and against what.

## 6. Done when

- every contradiction has both line references and a recommendation
- description-level ones are fixed by their owner
- design-level ones are listed, unfixed, with the trade-off stated in one
  sentence each
- `python3 -m pytest -q` still green — 339 at the time of writing

## 7. Reporting

`jira done`, then message `architect` with the commit you worked from, what you
read, what contradicts what, and which are design decisions waiting on me.
