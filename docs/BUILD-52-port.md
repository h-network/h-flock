# Build 52 — the adapter is a port

> ⚠ **Codemod change, on the PARKED branch.** Update
> `tools/rename_vocabulary.py` on `main`, regenerate `rename/vocabulary` from
> current `main`, push both. **Still parked, still not merged.**
> Owner: `api`.

## 1. Why this changes an executed rename

`DESIGN-layers` §2 now says the adapter **is** a switchport: it belongs to one
participant, it has a `port_type`, it builds and stamps `source`, and it filters
closest to the source. Build 49 renamed it `egress_adapter` / `ingress_adapter`;
that is superseded.

⚠ **The viewpoint clash is the reason.** `ingress`/`egress` are
participant-relative for the **queues** and cannot also name the port's halves,
because networking states a *port's* ingress from the **switch's** side. The
same file would be "the ingress filter" and `egress_adapter` at once.

## 2. The change

| build 49 produced | build 52 produces |
|---|---|
| `flock/adapter/` | `flock/port/` |
| `adapter/egress_adapter.py` (was `cli.py`) | `port/send.py` |
| `adapter/ingress_adapter.py` (was `runner.py`) | `port/deliver.py` |
| console script `flock.adapter` | `flock.port` |

⚠ **`agent:<name>:ingress` and `:egress` do NOT change.** Queues keep the
participant's viewpoint. Only the component and its halves are renamed.

⚠ **`subprocess.Popen(["flock.adapter", agent])`** in the switch must track the
console-script rename, or every delivery breaks. It is the one call site where a
missed rename is not a test failure but a dead bus.

## 3. ⚠ The custody records are an observable surface — DECIDE, do not drift

The five records carry `"module":"adapter"`. Renaming it to `"port"` changes
output that `clients/web`, the window-log tailer and every audit script parse.

**Decision: yes, rename it to `port`** — the vocabulary is worthless if the logs
speak the old one. But it is a wire-visible change, so it is **tier D**, it goes
in the tier D commit, and anything parsing `"module":"adapter"` moves with it.
Grep for the literal before you assume the codemod caught it; build 49 shipped
nine clients that a server-side rename had left behind.

## 4. Done when

- codemod on `main` produces the table in §2 from a clean checkout
- regenerated tree byte-identical to the pushed branch, `pytest` green
- zero `adapter` in `src/`; `ingress`/`egress` still present **only** as queue
  names and their key strings unchanged
- `"module":"port"` in the records, and no `"module":"adapter"` left anywhere
  including `clients/`
- ⚠ **branch pushed, NOT merged**

## 5. Reporting

`jira done`, then message `architect` with the counts, and say explicitly
whether anything outside `src/` was parsing `"module":"adapter"`.
