# Build 49 — the vocabulary, executed

> ⚠ **PARKED. Do not merge to `main`.** Branch `rename/vocabulary`, based on
> `main`, pushed to origin and left there until the new frame works. This is the
> operator's decision: land the renames somewhere real, keep them out of the
> tree until the design they serve is running.
>
> Owner: `api` — they own the wire surface (`API.md`, `clients/`), which is
> where tier D's risk lives. ⚠ It touches every lane's modules; see §5.

## 1. The five decisions, all already made

From [`GLOSSARY.md`](GLOSSARY.md). **Nothing here is open.** This build executes;
it does not decide.

| from | to | why | tier |
|---|---|---|---|
| `router` (the L2 component) | `switch` | it switches within a tenant; the HLD's own line 17 says `L2 switch` | A/B |
| `producer` / `recipient` | `source` / `destination` | the model says so; producer↔consumer is a different pairing | **D** |
| `vab` (the roster value) | `port_type` | it is an attachment type; `VAB` names the `pod:tenant:agent` address concept | C |
| `endpoint` | `provider` | `endpoint` means an addressable termination in the model this is built on | C |
| `adapter` (both directions) | `egress_adapter` / `ingress_adapter` | opposite sides of the switch shared one name; **participant-relative** | B |

## 2. Scale, measured

| | code | docs/prose |
|---|---|---|
| `producer`/`recipient` | 200 | 208 |
| `router` | 36 | 403 |
| `endpoint` | 47 | — |
| `vab` | 27 | — |

⚠ Tier D reaches **`clients/telegram/bot.py` and `clients/web/server.py`**, plus
`src/flock/bus/envelope.py` and `logging.py` — the two files whose correctness
builds 47 and 48 just established. Re-run the whole harness, not the unit suite.

## 3. ⚠ Deliver a CODEMOD, not a diff

**This is the point of the build.** A parked branch holding a 400-line
mechanical diff rots: every build on `main` conflicts with it, and rebasing a
rename is the worst kind of conflict resolution.

So commit **`tools/rename_vocabulary.py`** — a deterministic script that
transforms a clean checkout of `main` into the renamed tree — and the resulting
tree beside it. Then the branch is *regenerable*: when the new frame lands,
nobody rebases anything, they re-run the script against whatever `main` has
become and get a fresh branch.

The script must be idempotent, must refuse to run on a dirty tree, and must
print a summary count per rename so the diff can be checked without reading it.

## 4. Tier by tier — do them as separate commits

- **A — prose.** `router` → `switch` in `docs/`. Free, reversible, do first.
- **B — identifiers.** `router` → `switch` in code; module `flock/router` →
  `flock/switch`; the two adapter names. The suite catches breakage.
- **C — Redis keys and env vars.** `endpoint` → `provider`, `ENDPOINT_*` →
  `PROVIDER_*`. ⚠ **A running tenant breaks without dual-read.** Write the
  migration or state plainly that it needs a fresh tenant — do not leave it
  implied.

  ⚠ **`vab` → `port_type` was listed here and that was my error. It is tier D.**
  `vab` is a **wire field**: it is the `StartAgent` payload key and a
  `GET /agents/{agent}` response field, which `BUILD-45` §4 defines as tier D.
  Tiering it C meant the server and `API.md` were renamed while **nine client
  files were not**, and the failure is silent rather than loud —
  `control/openers.py` reads `payload.get("port_type", "tmux")`, so a client
  still sending `"vab": "api"` does not error, it **enrols as a tmux
  participant** and gets a window instead of a mailbox. The web client's own
  tests pass because `clients/web/server.py` mocks the old response shape.
- **D — wire.** `producer`/`recipient` → `source`/`destination` in the envelope,
  the API response shapes, `API.md`, and both clients. **Envelope v2.**

⚠ **Keep D in its own commit.** It is the one that must land before any fork,
and it is the one most likely to be cherry-picked ahead of the others.

## 5. Ownership, and why one lane does all of it

`api` executes the whole thing. A mechanical rename split across three lanes on
one branch produces three-way conflicts in the same lines — the opposite of
parallel. `bus` and `tmux` have been told to leave `rename/vocabulary` alone.

## 6. Done when

- `tools/rename_vocabulary.py` regenerates the branch from a clean `main`
- four commits, one per tier, in order
- `python3 -m pytest -q` green on the branch (345 on `main` at the time of
  writing)
- `container/accept.sh` green, and `fabric-bench` at `STATIONS=100 ROUNDS=20`
  delivering 2,000 of 2,000 with zero dead letters — ⚠ **one h-flock tenant at a
  time on the lab**
- ⚠ **pushed to `origin/rename/vocabulary` and NOT merged**

## 7. Reporting

`jira done`, then message `architect` with the commit, the per-tier counts the
script printed, whether tier C needs a fresh tenant or got a migration, and
anything the rename revealed that the inventory missed.
