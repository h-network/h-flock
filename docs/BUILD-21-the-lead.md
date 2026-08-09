# Build 21 — the lead, named

> An agent that knows *who* leads acts on it. One that knows a lead *exists* has
> to go and look, and does not.
>
> **Base on `main`.** Branch `<lane>/build-21-the-lead`, push to origin.

## 1. What changes, and why it overrides build 20 §C

Build 20 put the **rule** in the guide and the **name** in `office peers`, on the
grounds that a guide is written once and the roster changes. That reasoning was
sound and the result is weaker in practice: an agent reading *"this office has a
lead — `office peers` shows who"* has to take an extra step to act, and does not.

⚠ **Name the lead in the guide.** Observed in h-office, where agents follow the
lead's direction reliably — the guide names them. Staleness is the smaller risk:
a lead rarely changes, and an agent that acts on a name beats one that ignores an
abstraction.

## 2. The lead is the first agent created

`AGENTS` has an order. The roster is a HASH and does not — which is why every
"first agent" today is `sorted(...)[0]`, i.e. **alphabetically** first, and works
only because `architect` sorts early (`SPRINTS-next` §1).

**The entrypoint records it, once, at boot:**

```
  <prefix>:lead     STRING     the first name in AGENTS
```

⚠ **This is derived state, not configuration.** It is not `AGENT_LEAD`, which was
specced, built and reverted — that asked an operator to set separately what the
roster already knows. This copies the order out of a value that has one, at the
only moment that order is visible.

⚠ **Nothing else may set it.** Not a flag, not an env override, not a command. If
someone wants a different lead, they order the agents differently.

⚠ **`sorted(...)[0]` stops being the lead.** Fix `office peers` to read the key.
Leave `flock.tmuxhost`'s choice of first *window* alone — that is a layout
question, not an authority one, and conflating them is how this got confusing.

## 3. Two guides, not one

`generate_agents_md` takes the lead's name and writes one of two sentences, near
the top:

**In the lead's own guide:**

> You are the lead of this office. The other agents follow your direction, and
> yours is the account that decides when something is done.

**In every other guide:**

> `<lead>` is the lead of this office. Their direction is the office's direction.

⚠ **One sentence each, near the top.** `TODO.md` is blunt: agents stop reading
early, and every paragraph added pushes something out of the part that gets read.

⚠ **Say it plainly.** "Has standing to direct" is not a phrase an agent acts on.
The h-office wording works because it is unambiguous about what to *do*.

⚠ **No lead key yet — say nothing.** An office mid-migration has no `lead`; the
guide then omits the sentence entirely rather than guessing or naming the
alphabetically first agent.

## 4. The name carries weight of its own

`setup.sh` already defaults agent #1 to `architect`, and that is not decoration —
an authoritative name is doing work the roster cannot. Keep it, and keep the
suggestion list pointed at names that read as roles.

⚠ **Do not enforce it.** Someone may legitimately call their lead `chief` or
`lead-engineer`. The default suggests; the guide names whatever it finds.

## 5. Known and accepted: the guide is written once

If the lead is retired, other agents' guides still name them until their windows
are recreated. **Accepted**, not overlooked:

- a lead changing is rare, and a `letGo` of the lead is rarer still
- the alternative is re-writing every guide on every roster change, which is more
  moving parts than the problem justifies
- `office peers` reads the key live, so the current answer is always available to
  an agent that looks

Record it in `TODO.md` as a known staleness with this reasoning, so the next
person meets a decision rather than a bug.

## 6. Done when

- `<prefix>:lead` is the **first name in `AGENTS`**, not the alphabetically first
- an office whose first agent is `zeus` has `zeus` as lead, and `peers` says so
- the lead's guide says it is the lead; every other guide names them
- an office with no `lead` key writes neither sentence
- `office peers` marks the lead from the key, not from `sorted(...)[0]`
- `TODO.md` records the write-once staleness

## 7. Reporting

`jira done`, then message `architect` with the key, both guide sentences as
written, and status. ⚠ Test with a first agent whose name does **not** sort
first — that is the whole point of the change.
