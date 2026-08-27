# Telegram Bot Client (`clients/telegram/`)

A Telegram bot client that talks to an **h-flock** tenant over HTTP, allowing a user to communicate with the `architect` agent from Telegram.

---

## 1. Overview & Architecture

- **Participant Enrolment:** On startup, the bot enrols as a participant named `telegram` on the bus (`StartAgent` with `port_type: "api"`), retrying with backoff for up to 60s — `container/entrypoint.sh` starts the api door and this bundled client within the same instant, no readiness wait, so a single early attempt can lose that race (measured live).
- **Fire-and-forget prompts, delivery-side pushes replies:** A plain text message posts the envelope (`POST /agents/{agent}/envelopes`, always `202` immediately) and returns right away — no wait loop. `ReplyPusher`, a background thread, independently polls this bot's own mailbox (`GET /agents/telegram/messages`) and pushes each new reply into the chat as it arrives, on its own schedule. This matches how delivery actually works: nothing in the switch/port/api chain waits on anything, so nothing here should either.
  ⚠ **This replaced an earlier design that blocked inline** — `handle_user_prompt` used to poll-and-wait for a reply, unbounded, inside the same loop that read Telegram's `getUpdates`. One chat's unanswered prompt froze the *entire* bot, for every chat, until that one exchange resolved (measured live on the acceptance VM: the poller sat on one cursor for minutes while every message sent afterward went unread). Removed entirely rather than patched.
- **`blocked` Visibility:** If `architect` is `blocked`, the bot immediately reports `"architect is not accepting messages right now"` instead of posting.
- **Cursor Persistence:** `ReplyPusher` persists its mailbox cursor to disk (`cursor.json`) as it delivers each reply, and — like `AlertPusher` — seeds a fresh cursor store from the mailbox's current tail rather than replaying history on first run.
- **Discoverable commands:** `/menu`, `/status`, and `/voice` are registered with Telegram itself via `setMyCommands` at enrol time, so they show up in the client's own `/` command picker instead of requiring the user to know and type them blind.
- **Text-to-Speech (TTS) Voice Replies:** Spoken voice replies via Microsoft Edge's neural TTS voices (`edge-tts` package, PyPI) using Telegram's `sendVoice` endpoint. Declared dependency in `pyproject.toml`. Spoken voice replies are opt-in per tenant (`TELEGRAM_VOICE=1`, prompted during `setup.sh`) and opt-in per chat via `/voice` or the sticky menu toggle.
- **Inbound messages are restricted to `--chat-id`/`TELEGRAM_CHAT_ID`.** Every real Telegram update funnels through `_dispatch_update`, which drops anything from a different chat *silently* — no reply, no answered callback query — so an unauthorized sender learns nothing, not even that a bot is listening. ⚠ **No configured chat_id refuses everything, not the reverse**: the menu now reaches hire/retire/pause/resume/broadcast, so "whoever messages first" stopped being an acceptable identity check the moment those landed. This only affects manual/ad-hoc runs without `--chat-id` — `setup.sh`'s normal flow requires both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` before it enables the bot at all, so a real deployment always has one. CLI-driven one-shots (`--prompt`/`--status`/`--menu`, dry-run mode) call handlers directly and never go through this check — they're operator shell access, not untrusted network input.

---

## 2. Configuration & Running

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `FLOCK_API_URL` | `http://localhost:8080` | Base URL of the h-flock REST API service |
| `FLOCK_API_TOKEN` | *required* | Bearer API token for authentication |
| `TELEGRAM_BOT_TOKEN` | *optional* | Telegram Bot API token (from @BotFather) |
| `CURSOR_FILE` | `cursor.json` | Path to store `ReplyPusher`'s mailbox cursor |
| `TELEGRAM_CHAT_ID` | *optional* | Fixed chat for `--prompt`/`--status` one-shots, live alert push (§2b), **and the only chat the bot will respond to** — no reply, no push, no menu action for anyone else |
| `ALERTS_CURSOR_FILE` | derived from `CURSOR_FILE` | Path to store the alerts-stream cursor, kept separate from the mailbox cursor |
| `NO_ALERT_PUSH` | unset | Set to `1` to disable live alert push even when `TELEGRAM_CHAT_ID` is set |
| `TELEGRAM_VOICE` | `0` | Set to `1` to enable the spoken TTS voice replies feature in this tenant |
| `TTS_VOICE` | `en-US-AvaNeural` | Default Microsoft neural TTS voice for spoken replies (e.g. `en-US-AvaNeural`) via `edge-tts` |

### Running in Dry-Run Mode (Without Telegram Token)

When `TELEGRAM_BOT_TOKEN` is not supplied (or `--dry-run` is passed), the bot operates in **dry-run mode**, sending real envelopes and state requests to h-flock while printing all formatted Telegram message operations (`sendMessage`, `sendVoice`, `editMessageText`, `sendChatAction`) directly to stdout:

```bash
# Perform status check against real h-flock data
python3 clients/telegram/bot.py --api-token "$FLOCK_API_TOKEN" --status

# Post a prompt to architect and return immediately (fire-and-forget — see §1;
# the reply, if any, is ReplyPusher's job, not this one-shot invocation's)
python3 clients/telegram/bot.py --api-token "$FLOCK_API_TOKEN" --prompt "can you check the auth change?"
```

### CLI Command Options

```bash
python3 clients/telegram/bot.py \
  --api-url http://localhost:8080 \
  --api-token "$FLOCK_API_TOKEN" \
  --bot-token "$TELEGRAM_BOT_TOKEN" \
  --cursor-file cursor.json \
  --agent architect \
  --voice \
  --tts-voice en-US-AvaNeural \
  --dry-run \
  --prompt "can you check the auth change?"
```

---

## 2a. Menu: a pinned keyboard, not a one-off message

Sending `/menu` (registered with Telegram, so it's in the client's `/` picker
too) shows a **sticky keyboard** — `ReplyKeyboardMarkup`, pinned at the bottom
of the chat across messages, rather than an inline keyboard attached to one
message that scrolls away. Its eight buttons are the top-level office options
— built against `CONTRACTS.md`/`API.md`/`control/openers.py`, not `office`'s
own (narrower) argparse surface, per office-sme:

- **📋 Overview** — presence and open ticket (`doing[0]`) for every
  `port_type: "tmux"` agent in the roster. Excludes api clients (like this bot
  itself) and `host`, the same filter the web console uses for lifecycle
  controls.
- **🎫 Add ticket** — pick an agent from an inline sub-menu, then title,
  description (`-` to skip), then a priority (Low/Normal/High, tap only — see
  below). `/cancel` aborts at any text step. Posts `AddTicket` to `POST
  /agents/{agent}/envelopes`.
- **⏯ Lifecycle** — pick an agent from an inline sub-menu, then Pause, Resume,
  or Retire:
  - Pause/Resume post `PauseAgent`/`ResumeAgent` to `POST /agents/host/envelopes`.
  - **🗑 Retire** requires **typing the agent's name exactly** to confirm — the
    same pattern `clients/web/ui/lifecycle.js` uses, not a yes/no tap.
    `StopAgent` removes roster membership and identity state; queues and
    boards are kept for a later re-hire. A mismatched name re-prompts rather
    than cancelling, same as the web console's disabled-until-match button.
- **🔔 Alerts** — see §2b.
- **🎯 Message: `<agent>`** — pick which agent *this chat's* plain-text
  prompts (and `/status`) go to. Per-chat, not global: `--agent` is only the
  default until a chat picks one via this button. **This button's own label
  is dynamic** — it shows the chat's current target and updates the moment it
  changes, the one part of the keyboard that isn't a fixed constant (see
  `TelegramBot._sticky_keyboard`).
- **➕ Hire** — name (validated client-side against the same rule
  `clients/web/ui/lifecycle.js` uses: lowercase/digits/hyphens, not all
  digits, not a reserved word), then optional profile, then optional
  provider (`-` to skip either). Posts `StartAgent` with `port_type: "tmux"`,
  `cli: "claude"`. Unlike retire, hiring is not destructive — no identity or
  queues are ever removed — so it skips a type-the-name confirmation.
  ⚠ **No profile picker**: `office profiles` reads Redis directly and has no
  REST equivalent, so this client cannot list valid accounts ahead of time. A
  bad profile name still comes back as a clear `422` — and the api's error
  conveniently lists the valid ones (`control/openers.py`'s
  `available_profiles` check).
- **📢 Broadcast** — type a message, sent to every agent (`POST
  /agents/all/envelopes`).
- **🔊 Voice: ON / 🔇 Voice: OFF** — toggle spoken text-to-speech voice replies
  for this chat. Dynamic button label reflects current chat state (`/voice` command
  also toggles this).

⚠ **`Command` is deliberately not exposed here**, same as the web console
(`clients/web/SPEC.md` §6): it pastes bare text into a pane and *executes*
it. If an operator wants to run something, they can type it in the terminal,
where they can see what they're doing — a chat button is the wrong place for
that decision.

⚠ **Sticky-keyboard taps arrive as ordinary text messages** — Telegram sends
the button's label back as if the user typed it, with no `callback_query`.
`handle_text_message` matches the label against `TelegramBot.STICKY_LABELS`
(exact match for the six fixed buttons) or the `🎯 Message: ` prefix (for the
one dynamic button) before falling through to "this is a prompt for the
chat's target agent". Sub-flows one level down (agent pickers, Lifecycle's
Pause/Resume/Retire choice, Message-agent, Add Ticket's priority buttons) stay
**inline** — contextual, one-shot choices tied to a specific message, which is
what inline keyboards are for; the sticky keyboard is for top-level nav that
should always be one tap away without re-sending `/menu`.

While a chat has an open multi-step flow (Add Ticket, Hire, Retire,
Broadcast), its next plain text message is consumed as that flow's answer
rather than sent to `--agent` as a prompt (and takes priority over a
sticky-keyboard label, so typing a title that happens to match a button label
is still treated as the title).

Try it without a bot token: `python3 clients/telegram/bot.py --api-token "$FLOCK_API_TOKEN" --menu`.

---

## 2b. Alerts

**🔔 Alerts** (one of the four sticky-keyboard buttons, §2a) shows the tenant's recent
watchdog alerts on demand via `GET /alerts`, and — the more valuable half —
`AlertPusher` proactively pushes each *new* alert to `--chat-id`/
`TELEGRAM_CHAT_ID` as it happens via `GET /alerts/stream`, running in a
background thread alongside the normal polling loop. Disable it with
`--no-alert-push` / `NO_ALERT_PUSH=1`; it is skipped automatically when no
chat id is configured (the bot cannot push into a chat it has never heard
from).

⚠ **Only three alert kinds ever reach either surface: `blocked`, `stalled`,
`credential`.** These are exactly what `GET /alerts`/`GET /alerts/stream`
document (API.md's Watchdog Alerts Feed). The two newer, lead-only alerts —
`doing_duration` and `todo_duration` (the "unpicked ticket" one) — are pasted
directly into the *lead's* tmux pane as an ordinary `Message` envelope
(`flock/watchdog/service.py`'s `_notify_lead`, confirmed against `_check_doing_duration`/
`_check_todo_duration`), and never touch the alerts stream at all. There is
currently no API surface — REST or SSE — that exposes them to anything but
the lead's own pane, so this bot cannot surface them regardless of which
agent it targets. Flagged to architect as a possible follow-up (e.g.
mirroring them onto the alerts stream too), not built here — it was out of
this ticket's scope and text-matching the lead's ordinary conversation
mailbox to guess which messages are secretly alerts would be fragile.

`GET /alerts` has no "give me the most recent N" query — without `after` it
reads from the *oldest* stored entry, same as every other stream endpoint
here. The on-demand view therefore fetches up to the retention cap (1000)
and takes the tail client-side; `AlertPusher` avoids the equivalent problem
on first run by seeding its cursor from `next_cursor` (the current tail)
instead of streaming from the beginning, so it does not replay the whole
retained history as if every alert were new.

---

## 3. Documentation Gaps in `docs/API.md`

Built strictly against [`docs/API.md`](../../docs/API.md). The following gaps and ambiguities were encountered:

1. **Presence `blocked` State Omission in §5 Header**:
   Section 5 under `GET /agents/{agent}` (line 248) states: *"returns queue depths and presence status (working, idle, unknown)"*. It omitted `blocked` as a possible presence state in that section, even though `blocked` is a critical presence state documented in `CONTRACTS.md` and `HLD.md`.

2. **Re-enrolment Idempotency Behavior**:
   Sections 3 and 5 document `POST /agents/host/envelopes` with `StartAgent` and `port_type: "api"` for enrolling application clients, but do not state whether re-enrolling an already enrolled client (e.g. upon client restart) is idempotent or what HTTP status/body is returned.

3. **Task Board Ticket Schema Variability**:
   Section 5 gives an example response for `GET /agents/{agent}/board` with task objects containing `id`, `title`, `description`, `created_by`, `status`, `created_ts`, and `priority`. However, for legacy tasks or raw string items, `API.md` does not explain whether task items can be non-dict objects or strings.

4. **SSE Event Stream Reconnection (Header vs Query Parameter)**:
   Section 4 documents both `?after=<cursor>` (query parameter) and `Last-Event-ID` (HTTP header) for resuming SSE event streams. It does not specify precedence if both are present or note browser `EventSource` constraints (where custom headers cannot be set).

5. **Activity Feed Event Kinds & Schema**:
   Section 5 notes that `tool` events carry a `tool` string (e.g. `"tool": "Bash"`), but does not explicitly enumerate all valid values for `kind` or state whether `tool` is null/absent for non-tool event kinds (`input`, `output`).

6. **No reverse/tail query on `GET /alerts` (or any stream endpoint)**:
   Without `after`, `GET /alerts?limit=N` returns the *oldest* `N` stored entries (`xrange(min="-")`), not the most recent — unintuitive for a "show me recent alerts" one-shot. A client wanting the tail must fetch up to the retention cap and slice client-side, as this bot does. Worth a line in API.md's §4a gotchas.

7. **The two newest watchdog alerts never reach `GET /alerts`**:
   `doing_duration` and `todo_duration` ("unpicked ticket") are delivered as a direct `Message` to the lead's tmux pane (`_notify_lead`), not written to the alerts stream `_alert` writes to. API.md's Watchdog Alerts Feed section reads as if it covers "alerts produced by `flock.watchdog`" generally; it does not mention this split, and nothing in the REST/SSE surface exposes those two kinds at all.

8. **The account/profile registry has no REST endpoint**:
   `available_profiles` (`bus/accounts.py`) — what `office profiles` reads and what `StartAgent`'s `profile` field is validated against (`control/openers.py`) — is direct-Redis only. A REST client can `StartAgent` with a `profile` and get a clear `422` naming the valid accounts if it guesses wrong, but cannot list them ahead of time to offer a picker. `office usage` is the same shape (direct Redis, no REST equivalent).

## TLS

`--api-url https://<host>:8080` reaches a door serving TLS. Certificates are
verified by default:

```bash
--ca-cert /path/to/ca.pem     # verify against this CA        (FLOCK_CA_CERT)
--insecure                    # skip verification entirely    (FLOCK_INSECURE=1)
```

⚠ **`--insecure` is for the self-signed certificate `setup.sh` generates.** It
keeps the traffic encrypted but stops authenticating the door, so it says
nothing about who answered. Prefer `--ca-cert` wherever the certificate has an
issuer worth checking.

⚠ **Neither option touches the Telegram Bot API.** `api.telegram.org` is a
public host with a real certificate and stays verified — the context is handed
to the h-flock client only.
