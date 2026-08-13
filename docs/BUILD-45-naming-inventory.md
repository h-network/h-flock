# Build 45 — the vocabulary, as it actually is

> ⚠ **Inventory only. Rename nothing.** This build produces a table; the words
> get decided afterwards by the operator, whose model the names come from.
>
> **Base on `main`.** Branch `<lane>/build-45-naming`, push to origin.

## 1. Why

The design has been one consistent model since January — a network: switch,
ports, addresses, routing domains. The **names carry that intent and the intent
was never written down**, so anyone reading the repo reconstructs a plausible
substitute instead. Two examples found this week, both by reading the docs
against each other:

- **`VAB`** is documented as *"virtual agent base"* in the first architecture
  commit and everywhere since. That is not what it was coined for, and the
  expansion only makes sense for one of its three values — a mailbox is not an
  agent base, and neither is `control`.
- **`endpoint`** means the model an agent talks to (`agent:<name>:endpoint`,
  `ENDPOINT_*`), while the same word means a network termination point in the
  model the design is built on. Ambiguous in both directions at once.

⚠ **This is not a claim that the names are wrong.** It is a claim that their
meaning lives outside the repository, which is a defect regardless of which word
wins.

## 2. What to produce

One table per module you own, committed as `docs/NAMING-<lane>.md`:

| name | where it lives | kind | what it means, in one line | networking analogue, if any |
|---|---|---|---|---|

**`kind`** is one of: `doc term`, `identifier` (function, class, variable),
`redis key`, `env var`, `wire` (envelope field or API response field).

⚠ **Cite `file:line` for at least one occurrence of each.** A name you cannot
locate is not in the inventory.

## 3. The four things actually being looked for

1. **One word, two meanings.** `adapter` is both `adapter/cli.py` (an agent
   putting an envelope *on* the bus) and `adapter/runner.py` (delivering one
   *off* it) — opposite sides of the switch sharing a name.
2. **Two words, one meaning.** Where the code says one thing and the docs say
   another for the same concept.
3. **A name whose meaning you cannot determine** from code and docs alone.
   ⚠ **This is the most valuable output of the build.** Say so plainly: "I could
   not tell what this means without asking." That is a finding about the
   repository, not about you.
4. **A name that contradicts the model.** The design is a network. A name that
   maps onto it — `roster` as a MAC table, `kind` as an ethertype — earns its
   place. One that doesn't should say what it actually is.

## 4. Tier every row by what changing it would cost

| tier | scope | why it matters |
|---|---|---|
| **A** | docs and comments | free, reversible |
| **B** | internal identifiers | safe; the suite catches breakage |
| **C** | redis keys, env vars | a running tenant breaks without dual-read or migration |
| **D** | wire — envelope fields, API response fields | envelope v2, client updates, `API.md` |

⚠ **Tier is not importance.** A tier-D name may be perfect and a tier-A name
badly wrong.

## 5. Ownership

| lane | modules |
|---|---|
| `bus` | `flock/bus`, `flock/router`, and every Redis key shape they define |
| `api` | `flock/api`, `flock/session`, and the wire surface in `API.md` |
| `tmux` | `flock/tmux`, `flock/tmuxhost`, `flock/adapter`, `flock/control`, `container/` |
| `architect` | `HLD`, `CONTRACTS`, cross-cutting terms, and merging the tables into one glossary |

## 6. Done when

- your table exists, every row cited and tiered
- collisions, drifts and undeterminable names are called out explicitly
- ⚠ **nothing is renamed** — not in code, not in docs
- `python3 -m pytest -q` still green (339 at the time of writing), which should
  be trivially true since this build changes no code

## 7. Reporting

`jira done`, then message `architect` with the commit, the path to your table,
and — separately, in the message — **the three names you would most like
changed and why**. That opinion is wanted; acting on it is not.
