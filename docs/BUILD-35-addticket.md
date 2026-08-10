# Build 35 — a ticket should not need a window

> Two things, in this order: stop losing tickets, then confirm the ones that
> land. `bus` owns both — the board is yours.
>
> **Base on `main`.** Branch `bus/build-35-<piece>`, push to origin.

## 1. Stop requiring a window

`add_ticket_opener` calls `list_windows` and raises `DeadLetter("window_missing")`
when the agent has none — even though the ticket is only a Redis write and the
opener pastes nothing.

⚠ **The board is pulled.** A ticket written to `tasks.todo` waits until the agent
runs `office take`. There is no reason it must exist *now*, and a window that is
missing for a moment — crashed, or not yet reconciled — is exactly when work is
most likely to be handed out.

⚠ **Pause is already safe**, so this is not about pausing: `pause_agent` calls
`interrupt_window`, not kill, and the adapter checks the `paused` key before
delivering. The exposure is a crashed or not-yet-built window.

**Write the ticket regardless of the window.** Then decide the edge and say
which you chose:

- an agent in the roster with no window — write it, it waits. This is the case
  that loses work today
- an agent **not** in the roster — the router already dead-letters before the
  adapter sees it, so nothing to do
- ⚠ **`StopAgent` retains boards deliberately** (`purge_agent` keeps queues and
  board), so a ticket outliving a retirement is existing behaviour, not new

## 2. Then confirm the write

`Message` and `Command` both call `mark_delivery_pending()`, so they are judged
and can become `blocked`. `AddTicket` is the only delivery kind never confirmed.

⚠ **The existing mechanism does not transfer.** Verification watches for a later
`input` event in the CLI's session file, because a paste is only proven by the
agent consuming it. `AddTicket` pastes nothing, so there is no input to wait for
and `pending.verify` is the wrong tool.

The honest equivalent is confirming the thing it actually did: **the board write
happened**. It is synchronous and cheap — read back the list length, or the
ticket id, and emit a lifecycle record either way.

- ⚠ **Do not invent a `blocked` for boards.** `blocked` means a delivery was not
  consumed; a written ticket that nobody has taken yet is the normal state of a
  board, not a fault
- a failed write must be a `DeadLetter`, like any other opener failure, so
  `receive` parks it and logs one terminal record (`CONTRACTS` §opener contract)

## 3. Done when

- a ticket delivered to an agent whose window is missing **lands on the board**
- the board write is confirmed, with a record when it is not
- `AddTicket` still pastes nothing and still produces no terminal output
- ⚠ **demonstrated on the lab**: kill an agent's window, deliver a ticket, show
  it on the board, then let the window come back and take it

## 4. Reporting

`jira done`, then message `architect` with what you changed, the edge you chose
for a roster-less agent, and the run.
