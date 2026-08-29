# STARTING — picking this up cold, on a fresh h-flock office

For whoever spins up next: a new h-flock tenant, hired to work *on* h-flock
itself (the same dogfooding loop the README's "Built by an office of agents"
section describes). This file is the entry point — it doesn't repeat what's
already written elsewhere, it tells you which file answers which question.

⚠ **What carries over and what doesn't.** Everything in `docs/` and `git
log` carries over — that's the whole point of writing it down. What does
**not** carry over is anything only said in a chat between the previous
operator and lead and never turned into a doc row or a ticket. If something
feels like it's missing context, it might genuinely be missing — check
`TODO.md` and the board before assuming you're wrong.

## 1. Orient: who's here, who owns what

```bash
office peers -i        # who's actually hired right now, colleagues + clients
office profiles        # every account, who's on it, who has no CLI login
office status           # who's working, on what, since when
```

Then read [`LLD-lanes.md`](LLD-lanes.md) — which lane owns which module,
derived from real merge history, not guessed. If it disagrees with `office
peers -i`, trust the live roster (§4 of that file says so explicitly).

## 2. Orient: what's designed, what's open, what order

| file | answers |
|---|---|
| [`HLD.md`](HLD.md) | how the pieces fit, the invariants — start here for the design itself |
| [`TODO.md`](TODO.md) | what's open right now, unordered, with why |
| [`SPRINTS.md`](SPRINTS.md) | what order to pick TODO rows in, batched, against which test run |
| [`STATUS.md`](STATUS.md) | known-wrong docs and merged-but-unverified work, as of its own write date — check that date before trusting it over the code |
| [`CHANGELOG.md`](CHANGELOG.md) | external-contract changes |

`TODO.md`'s own warning applies here too: **a row is a claim about the
tree, re-read it against the tree before you trust it.** Docs drift; code
and `git log` don't.

## 3. How this office actually works

There's no repo-level `CLAUDE.md`/`AGENTS.md` checked in — each agent's
guide is generated fresh at hire time by `flock.tmux.ops.generate_agents_md`
and written into their own window. Read the generated file in your own
`$HOME`, not a static doc, for the literal rules you're operating under
(reply discipline, branch-per-change, ask-before-destructive, the ack-loop
wording, etc.).

The operating conventions that aren't in the generated guide but matter for
picking this up specifically:

- **One ticket, one branch, one focused change.** Branch as
  `<lane>/<short-description>`, push, tell the lead. **The lead opens the pull
  request into `develop`**, reviews it there, and merges once CI passes — a
  lane never opens its own PR and never merges into `develop` or `main`
  directly. `develop` moves to `main` on its own release cadence, separate
  from any individual PR. The lead **deletes the branch on both sides** —
  remote and local — once merged. A pile of stale merged branches is a
  recurring failure mode here, not a hypothetical one; check `git branch -r
  --merged origin/develop` before assuming the branch list is clean.
- **A behaviour change ships with its docs, in the same branch.** Not a
  follow-up sweep — the sweep is for staleness that already happened, not a
  substitute for keeping docs current as you go.
- **Credentials**: never printed, never logged, never dumped to check
  presence (check presence only). Moving a real credential anywhere —
  scp'ing it, testing with it — needs an explicit, scoped yes from the
  operator each time, not standing permission from a prior yes.

## 4. If you're touching `port_type: openshell` specifically

Read [`LLD-port-openshell.md`](LLD-port-openshell.md) first — it has its
own live-verification history (§2a, §5) and open questions (§4) that
`HLD.md`'s one-line mention won't cover. The credential-transfer design
(claude: per-call env var; codex: write-then-wipe file; agy: blocked on a
missing binary in the default sandbox image) lives in
[`openshell-credential-transfer-design.md`](openshell-credential-transfer-design.md),
and the full SDK/gRPC surface — including what's real but still unused —
is in
[`openshell-sdk-surface-inventory.md`](openshell-sdk-surface-inventory.md).

## 5. First real move

Don't start writing code from a cold read alone. Check `office list` on
your own board, check `office status` for anyone mid-ticket, and check
`TODO.md`/`SPRINTS.md` for what's actually next — the same way any lane
picks up a shift here, not a special case for being new.
