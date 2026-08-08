# Build 13 — the public API reference

> Documentation for an **external developer** building an app against h-flock —
> a web front end, a macOS or iOS app, a Telegram bot. They will never see this
> repository.
>
> **Base on `main`.** Branch `api/build-13-public-api-docs`, push to origin.
> Deliverable: **`docs/API.md`**.

## 1. Who it is for, and what that rules out

Someone with an HTTP client and a token. They do not have the source, cannot
read a Python file to resolve an ambiguity, and cannot ask us.

⚠ **Every internal reference is a bug in this document.** No module paths, no
function names, no `src/…`, no "see `LLD-api` §4", no lane names, no build
numbers. If a rule only makes sense once you have read `CONTRACTS`, it is not
explained yet.

⚠ **They cannot see the code, so ambiguity is unresolvable.** Where we have been
writing *why* a decision went the way it did, this document instead has to be
exact about *what happens*: every status code, every field, what is optional,
what a missing value means. A sentence a reader could act on two ways is a
defect here in a way it is not elsewhere.

⚠ **Do not describe anything that is not built.** No roadmap, no "coming soon".
An external reader treats the document as the contract.

## 2. What it must let them build

The test: **someone reads only this and ships a Telegram bot.** Concretely, they
must be able to work out, without guessing —

- how to authenticate, and what happens when they do not
- how to register their app so agents can reply to it
- how to send a message to an agent, as their app rather than as "the api"
- how to receive replies, both by polling and live
- how to resume after their process restarts, without losing or repeating messages
- how to read task boards
- how to add, retire, pause and resume agents
- what every error means and which are worth retrying

## 3. Shape

Yours to arrange, but it has to cover these and a reference section is not
enough on its own — the concepts come first or nothing else parses.

**Concepts.** An office of agents; each has a **name** and that name is the only
address. An **app is a participant too** — it enrols, gets a name, and agents
reply to it exactly as they reply to each other. An **envelope** is what travels;
a **kind** says what sort of thing it is; a **mailbox** is where an app's
messages wait. Boards are **pulled**, so nothing is ever pushed at an agent.

**Getting started.** Base URL, port, bearer token, then the shortest path that
works end to end: enrol → send → read the reply. A reader should have a working
loop before they meet a single option.

**Reference.** Every endpoint: method, path, path and query parameters, request
body, response body with a **real example**, and every status code it returns.

**Receiving.** The part most likely to be got wrong, so give it its own section:
cursors, what a cursor is, where the first one comes from, what happens if you
omit it, how to resume, and the SSE event format including reconnection.

**Terminals.** The WebSocket door — what it is for and, explicitly, what it is
*not* for. A reader must come away knowing they should never parse terminal
output to obtain an answer; that is what messages are for.

**Limits and behaviour worth knowing.**

- `POST` returns **202** — accepted, not answered. A reply, if any, arrives in
  the mailbox later. Agents take seconds to minutes; nothing is synchronous.
- **A reply may never come.** An agent can be busy, wedged, or simply choose not
  to answer. An app must be built for silence.
- Mailboxes retain roughly the **last 1000 messages**. A client away longer than
  that has lost its place, and must be told so rather than shown a gap.
- Message **ordering per mailbox** is the stream order; say what is and is not
  guaranteed.
- The token is **shared, not per-app**. An app's declared identity is checked
  against the roster but not proven. Say so plainly — someone deciding where to
  terminate TLS or whether to expose the port needs to know.

**A worked example.** One end-to-end walkthrough — enrol, send, receive, resume —
in `curl`, and one in a real language. This is the section people actually read.

## 4. Verify it, do not transcribe it

The tenant on the lab host is free and rebuilt on current `main`. **Run every
call you document** and paste real responses.

⚠ **Real output, not plausible output.** Invented example bodies are how a
reference goes subtly wrong — a field named slightly differently, a status code
that is actually 404. If a call cannot be run, leave it out and say why in your
report rather than describing it from the code.

⚠ **Check the failures too**, not only the happy path: no token, bad token,
unknown agent, unenrolled client, a cursor that has fallen off the end.

## 5. Done when

- a reader with only `docs/API.md` and a token can enrol a client, send to an
  agent, and read the reply
- every endpoint on both doors is documented with a real request and response
- reconnect-without-loss is explained well enough to implement
- no internal path, module, file or section reference appears anywhere in it
- `README.md` links to it — one line, I will place it

## 6. Reporting

`jira done`, then message `architect` with the path, the section list, and
**anything you found while verifying that the API does wrong** — a bad status
code or a confusing shape found now is worth more than the document.
