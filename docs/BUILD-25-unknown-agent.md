# Build 25 — an unknown agent is a 404

> **Base on `main`.** Branch `api/build-25-unknown-agent`, push to origin.

## 1. What it answers today

`GET /agents/<name>` returns **`200` with zero depths** for a name nobody
enrolled. `404` comes only from a name that breaks the segment rule.

⚠ **So an app cannot tell a typo from an idle agent**, and it never finds out:
the `POST` is accepted, the envelope dead-letters where the client cannot see,
and every read says zero. Each layer answers truthfully and the sum misleads.

## 2. The check

**One `HEXISTS` on the roster, before anything else.** `flock.bus.is_member`
already exists and the router already uses it.

| | |
|---|---|
| name not in the roster | **`404`** |
| name in the roster, holding nothing | **`200`** with empty state, as now |

⚠ **Those two are different questions and the confusion between them is why this
sat open.** An enrolled agent with an empty board, an empty mailbox or no
presence is `200` — that answer is correct and must not change. Only *no such
agent* becomes `404`.

Apply it to the reads: `GET /agents/{agent}`, `/board`, `/messages`,
`/activity`, and their `/stream` forms.

## 3. `POST` — and the one edge that would break it

⚠ **`all` is not a roster member.** It is the broadcast address, reserved in
`flock.bus.keys`, and `HEXISTS roster all` is `0`. A membership check applied
naively to `POST /agents/all/envelopes` **turns broadcast into a 404** and breaks
it for every client.

So on `POST`: `404` when the recipient is neither a roster member nor `all`.

⚠ This does not make the api validate envelopes. It reads the roster — the same
source the router reads a moment later, so the two cannot disagree about who
exists. What the api still must not do is judge `kind` or payload.

⚠ **A race is fine.** An agent hired between the check and the send falls through
to the router and dead-letters exactly as today. The check is there to catch a
typo, not to be a lock.

`host` and `api` are roster members, so lifecycle posts are unaffected — confirm
that rather than assuming it.

## 4. Done when

- `GET /agents/nosuchagent` → `404`; an enrolled agent holding nothing → `200`
- the same for `/board`, `/messages`, `/activity` and both `/stream` forms
- `POST /agents/nosuchagent/envelopes` → `404`
- **`POST /agents/all/envelopes` still works** — the check on this one matters
  more than all the others
- `POST /agents/host/envelopes` still works, so `hire` and `letGo` are unaffected
- `API.md` says what `404` means now: the agent does not exist, as distinct from
  having nothing

## 5. Reporting

`jira done`, then message `architect` with status and the observed results for
`all` and `host` specifically.
