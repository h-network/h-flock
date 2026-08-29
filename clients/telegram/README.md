# Telegram Bot Client (`clients/telegram/`)

A Telegram bot client that talks to an **h-flock** tenant over HTTP, allowing a user to communicate with the `architect` agent from Telegram.

---

## 1. Overview & Architecture

- **Participant Enrolment:** On startup, the bot enrols as a participant named `telegram` on the bus (`StartAgent` with `port_type: "api"`), retrying with backoff for up to 60s — `container/entrypoint.sh` starts the api door and this bundled client within the same instant, no readiness wait, so a single early attempt can lose that race (measured live).
- **Fire-and-forget prompts, delivery-side pushes replies:** A plain text message posts the envelope (`POST /agents/{agent}/envelopes`, always `202` immediately) and returns right away — no wait loop. `ReplyPusher`, a background thread, independently polls this bot's own mailbox (`GET /agents/telegram/messages`) and pushes each new reply into the chat as it arrives, on its own schedule. This matches how delivery actually works: nothing in the switch/port/api chain waits on anything, so nothing here should either.
  ⚠ **This replaced an earlier design that blocked inline** — `handle_user_prompt` used to poll-and-wait for a reply, unbounded, inside the same loop that read Telegram's `getUpdates`. One chat's unanswered prompt froze the *entire* bot, for every chat, until that one exchange resolved (measured live on the acceptance VM: the poller sat on one cursor for minutes while every message sent afterward went unread). Removed entirely rather than patched.
- **`blocked` Visibility:** If `architect` is `blocked`, the bot immediately reports `"architect is not accepting messages right now"` instead of posting.
- **Cursor Persistence:** `ReplyPusher` persists its mailbox cursor to disk (`~/.flock/telegram.cursor.json` by default — see `--cursor-file` below) as it delivers each reply, and — like `AlertPusher` — seeds a fresh cursor store from the mailbox's current tail rather than replaying history on first run.
- **Discoverable commands:** `/menu`, `/status`, `/watch`, `/unwatch`, `/run`, and `/voice` are registered with Telegram itself via `setMyCommands` at enrol time, so they show up in the client's own `/` command picker instead of requiring the user to know and type them blind.
- **Text-to-Speech (TTS) Voice Replies:** Spoken voice replies via Microsoft Edge's neural TTS voices (`edge-tts` package, PyPI) using Telegram's `sendVoice` endpoint. Declared dependency in `pyproject.toml`. Spoken voice replies are opt-in per tenant (`TELEGRAM_VOICE=1`, prompted during `setup.sh`) and opt-in per chat via `/voice` or the sticky menu toggle (voice-enabled chats receive both the full text reply and the spoken voice audio).
- **Inbound messages are restricted to `--chat-id`/`TELEGRAM_CHAT_ID`.** Every real Telegram update funnels through `_dispatch_update`, which drops anything from a different chat *silently* — no reply, no answered callback query — so an unauthorized sender learns nothing, not even that a bot is listening. ⚠ **No configured chat_id refuses everything, not the reverse**: the menu now reaches hire/retire/pause/resume/broadcast, so "whoever messages first" stopped being an acceptable identity check the moment those landed. This only affects manual/ad-hoc runs without `--chat-id` — `setup.sh`'s normal flow requires both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` before it enables the bot at all, so a real deployment always has one. CLI-driven one-shots (`--prompt`/`--status`/`--menu`, dry-run mode) call handlers directly and never go through this check — they're operator shell access, not untrusted network input.

---

## 2. Configuration & Running

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `FLOCK_API_URL` | `http://localhost:8080` | Base URL of the h-flock REST API service |
| `FLOCK_API_TOKEN` | *required* | Bearer API token for authentication |
| `TELEGRAM_BOT_TOKEN` | *optional* | Telegram Bot API token (from @BotFather) |
| `CURSOR_FILE` | `~/.flock/telegram.cursor.json` | Path to store `ReplyPusher`'s mailbox cursor |
| `TELEGRAM_CHAT_ID` | *optional* | Fixed chat for `--prompt`/`--status` one-shots, live alert push (§2b), **and the only chat the bot will respond to** — no reply, no push, no menu action for anyone else |
| `ALERTS_CURSOR_FILE` | derived from `CURSOR_FILE` | Path to store the alerts-stream cursor, kept separate from the mailbox cursor |
| `NO_ALERT_PUSH` | unset | Set to `1` to disable live alert push even when `TELEGRAM_CHAT_ID` is set |
| `NO_ACTIVITY_PUSH` | unset | Set to `1` to disable live-updating progress messages while agents execute tools |
| `FLOCK_SESSION_URL` | derived from `FLOCK_API_URL` (`:8081`) | Base WebSocket URL for the Session door, used by `/watch` (§2d) |
| `TELEGRAM_VOICE` | `0` | Set to `1` to enable the spoken TTS voice replies feature in this tenant |
| `TTS_VOICE` | `en-GB-RyanNeural` | Default Microsoft neural TTS voice for spoken replies (e.g. `en-GB-RyanNeural`) via `edge-tts` |
| `PANE_WATCH_CHROME_DEFAULT` | `4` | `/watch`: bottom pane rows cropped as UI chrome (input box, shortcut hint, separators) |
| `PANE_WATCH_CHROME_OVERRIDES` | unset | `/watch`: per-agent chrome-row exceptions, `"agent=n,agent2=n"` — see §2d, Codex needs `5` |
| `PANE_WATCH_TAIL_LINES` | `12` | `/watch`: how many rows back from the bottom of the pane to look before cropping chrome |
| `PANE_WATCH_REFRESH_SECONDS` | `2.0` | `/watch`: seconds between pane refreshes |
| `PANE_WATCH_MAX_DURATION_SECONDS` | `600` | `/watch`: auto-stop a forgotten watch after this many seconds |
| `MINI_APP_URL` | unset | Public HTTPS URL for `clients/web/mini.html` — adds a 📊 Dashboard `web_app` button to the sticky menu (§2a) when set, omitted entirely otherwise. See `clients/web/README.md`'s Telegram Mini App section — that server is not started here and needs its own `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` to accept the button's login |
| `RUN_ALLOWED_COMMANDS` | `/clear,/compact` | `/run` (§2h): comma-separated exact-match allowlist of native CLI slash commands — global, not per-CLI/per-agent, see §2h |

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
  --session-url ws://localhost:8081/session \
  --api-token "$FLOCK_API_TOKEN" \
  --bot-token "$TELEGRAM_BOT_TOKEN" \
  --cursor-file ~/.flock/telegram.cursor.json \
  --agent architect \
  --voice \
  --tts-voice en-GB-RyanNeural \
  --pane-watch-chrome-overrides "backend=5,frontend=5" \
  --run-allowed-commands "/clear,/compact" \
  --dry-run \
  --prompt "can you check the auth change?"
```

---

## 2a. Menu: a pinned keyboard, not a one-off message

Sending `/menu` (registered with Telegram, so it's in the client's `/` picker
too) shows a **sticky keyboard** — `ReplyKeyboardMarkup`, pinned at the bottom
of the chat across messages, rather than an inline keyboard attached to one
message that scrolls away. Its buttons are the top-level office options
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
- **`@agent message text`** — a one-off override, not a persistent-target
  change: `@sme-2 can you check this?` reaches `sme-2` for that one message
  only, and the very next plain message still goes to whatever 🎯 Message
  agent has set. Deliberately anchored to the *start* of the text — an
  `@word` anywhere else in the message is ordinary content, not a second
  routing directive (Slack-style inline mentions notify; this one redirects
  the whole message, so unlike Slack it needs to be unambiguous about what
  it applies to). The name is validated against the same shape ➕ Hire
  enforces and the live roster (`_tmux_agents()`) before sending — an
  unknown name, a reserved word, or a real but non-tmux client (`telegram`
  itself, `host`) is refused with a plain-text error rather than silently
  dead-lettered. `@agent` with nothing after it prompts for a body instead
  of sending an empty message.
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
- **📊 Dashboard** *(conditional — only when `MINI_APP_URL` is configured)* —
  a Telegram Mini App `web_app` button, distinct from every button above:
  tapping it opens `clients/web/mini.html` inside Telegram's own WebView
  client-side and never arrives at `handle_text_message` as a message the
  way every other sticky-keyboard tap does. Read-only — see
  `clients/web/README.md`'s Telegram Mini App section for the auth flow
  and what it can and can't do.
- **🙈 Hide menu** — actually dismisses the sticky keyboard. A persistent
  `ReplyKeyboardMarkup` (`is_persistent: true`, what every keyboard this bot
  sends already sets) can't be dismissed from the phone itself — Telegram's
  own "collapse" gesture is a temporary panel toggle, not a removal, and the
  keyboard reappears on the next refresh. This button is the one thing that
  actually does it, by replying with `reply_markup: {"remove_keyboard":
  true}` (`ReplyKeyboardRemove`) instead of the normal keyboard.
  `/menu` (unchanged) brings it straight back.

⚠ **Full `Command` passthrough is deliberately not exposed here**, same as
the web console (`clients/web/SPEC.md` §6): it pastes bare text into a pane
and *executes* it, with no live view of the pane to confirm what actually
happened — the wrong shape for unbounded remote execution from a phone.
`/run` (§2h) is a narrower, later exception to that: a fixed, pre-vetted
allowlist of native CLI slash commands, typed by hand rather than one tap
on a button, not a reopening of full passthrough. See §2h for the reasoning
behind where that line is actually drawn.

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

## 2c. Live Activity Progress (Rolling `editMessageText`)

When a user sends a prompt to an agent via Telegram, the bot starts an activity watcher that tails the agent's real-time execution stream (`GET /agents/{agent}/activity/stream`). As the agent executes tools (`Bash`, `Read`, `Edit`, `Grep`, etc.) and transitions between states (`input`, `tool`, `output`), the bot maintains a live-updating message using Telegram's `editMessageText`:

```text
🛠 Activity (architect)
1. ✓ 💬 input received
2. ✓ Read
3. ✓ Grep
4. ⏳ Bash

⏳ still working… (updated just now)
```

- **Tool-Names Privacy Invariant:** Respects `HLD.md` §8 privacy boundaries — events carry tool names and lifecycle markers only, never arguments, parameters, file paths, or shell strings.
- **In-Place Updates & Throttling:** Edits are throttled to at most ~1/sec to comply with Telegram rate limits, keeping total rendered characters well below Telegram's 4096 cap via sliding window truncation for long execution runs. Redundant edits with identical text are skipped.
- **Completion & Coexistence with Replies:** When the agent finishes (when `ReplyPusher` delivers the reply from the mailbox), the activity message is finalized in place (`🛠 Activity (architect) · completed (4 steps)`), and the full final response (and voice note if enabled) is delivered as a fresh new message.
- **Disabling:** Disable live activity streaming by passing `--no-activity-push` or setting `NO_ACTIVITY_PUSH=1`.

---

## 2d. `/watch` — Live-Tail an Agent's Terminal (Rolling `editMessageText`)

A clearer alternative to guessing what an agent is doing from tool names: one
Telegram message showing an actual slice of the agent's tmux pane, refreshed
in place. This **replaces** an earlier "diff-triggered liveness pulse" design
(a `⏳ still working…` timestamp line bolted onto the activity message above)
that operators found unclear — this shows the content itself instead.

**Trigger.** Tap **👁 Watch** on the sticky menu (or send `/watch`) to pick an
agent from an inline list, or send `/watch <agent>` directly. One watch runs
per chat; starting a new one (any agent) replaces whatever was already
running there. `/unwatch`, or the **⏹ Stop watching** button attached to the
live message itself, ends it early.

**Source.** Reuses the Session WebSocket door's existing capture-pane
mechanism (`ws://HOST:8081/session`, `LLD-session.md` §2–3) — the bot has no
local tmux access at all, by design (`HLD.md` §7: `:8081` is terminal bytes
for a *person*, not a data path an app parses, except this one sanctioned
"watching an agent work" case). Rather than reconstructing a screen
client-side from the live `%output` diff stream, the bot asks for one fresh
snapshot per refresh tick via a small session-door protocol addition —
`{"subscribe": [agent], "mode": "read-only", "refresh": true}` — which
re-runs `capture-pane` for an already-subscribed agent instead of requiring
an unsubscribe/resubscribe round trip that would risk losing a live diff in
the gap.

**Content window.** Every `capture-pane` snapshot is up to the pane's full
120×32 screen (`LLD-tmux-host.md` §3); most of that is either stale
scrollback or the CLI's own input chrome, neither of which is "what the agent
just said". The bot looks at the last `PANE_WATCH_TAIL_LINES` rows (default
`12`) and crops the bottom `PANE_WATCH_CHROME_DEFAULT` rows (default `4`) —
net, roughly rows `[bottom-12 .. bottom-4]` — then trims rows from either edge
of what's left that are blank or match `_is_transient_chrome_line` (below).

⚠ **Chrome height is not the same across claude/codex/agy, and the bot
cannot ask which one an agent runs** (`GET /agents/{agent}` carries
`port_type` and presence, never `cli` — only `office peers -v`'s
`framework=<cli>` field reads that, from a Redis key (`resource: "launch"`)
the api door does not expose). Measured against
three live panes: claude and agy's Antigravity CLI both draw a 4-row bottom
*structural* chrome (separator / input line / separator / hint), Codex draws
5 (separator / blank / input box / footer status line). The default of `4`
is correct for two of three; `PANE_WATCH_CHROME_OVERRIDES` (same
`"name=value"` exceptions shape as `entrypoint.sh`'s `AGENT_CLIS`) lets an
operator who knows which agents run Codex correct those by name rather than
the bot guessing or mis-cropping silently.

⚠ **A second, state-dependent kind of chrome sits just above the structural
kind, and no fixed offset can crop it correctly.** A CLI's own
thinking-spinner ("✻ Churned for 20s", "Boogieing… (17s · ↓ 639 tokens)") and
update-nag banner ("✔ Update installed · Restart to update") are present or
absent depending on whether the agent is mid-turn or an update just shipped —
not on which CLI it is. Widening the crop only shifts where the leak lands;
first shipped (`PANE_WATCH_TAIL_LINES` `10`, no filtering) it leaked on a
codex pane and, checked again on a claude pane that happened to have both a
spinner and an update banner up at once, it was leaking there too. Filtered
by content instead (`_is_transient_chrome_line`, `bot.py`): update-banner
phrasing, a line ending in `tokens)`, claude's `done HH:MM AM/PM` completion
stamp, and a short (≤60 char) line matching `<word(s)> for Ns[ Ns]` — capped
in length so a genuine reply that happens to mention a duration mid-sentence
isn't mistaken for a spinner line. agy's own spinner text is unconfirmed —
none of the three lanes has captured it mid-turn yet — so it may need a
pattern added once it leaks somewhere.

**Refresh & stop conditions.** Polls every `PANE_WATCH_REFRESH_SECONDS`
(default `2.0`). Stops on any of: the **⏹ Stop watching** button or
`/unwatch`; `PANE_WATCH_MAX_DURATION_SECONDS` elapsing (default `600`, a
safety net against a forgotten watch); or the watched agent transitioning
from `working` to `idle` presence (`GET /agents/{agent}`) — a transition, not
a snapshot, so starting a watch on an already-idle agent doesn't end it
immediately. On any stop, the message is edited once more with the
last-known pane content plus a reason line, its **⏹ Stop watching** button
removed, and it is not touched again — the final state is what's left
behind, matching a normal Telegram message rather than one that looks
perpetually "live" after the bot has moved on.

---

## 2e. Receiving a Photo

Sending a photo used to be silently dropped — `_dispatch_update` only ever
looked at `message.text`, and a photo update carries `message.photo`/
`message.caption` instead, so it fell through with no reply and no record
anywhere. It now downloads the photo and sends a real `Attachment`-kind
envelope (`docs/CONTRACTS.md`) — file bytes on the bus, `content_base64`,
not a path shared out of band. An earlier version of this feature (before
the Attachment kind existed) saved the file under the agent's own workdir
and sent a plain `Message` naming the path; that's gone now that there's a
real envelope kind to send it as, and the tmux opener does the filesystem
work instead (`/workdir/<recipient>/attachments/<stream_id>/`, entirely its
own to create/write/clean up — confirmed directly with the tmux lane rather
than assumed. This client never touches a filesystem for a received photo
at all).

- **Routing is identical to a text message.** The caption is the
  `Attachment` envelope's `caption` field — the persistent chat target (🎯
  Message agent) unless the caption starts with `@agent`, which overrides
  the destination for this photo only, exactly like [§2a's
  `@mention`](#2a-menu-a-pinned-keyboard-not-a-one-off-message) (same
  validation, `_validate_mention_target`, shared with the text path rather
  than reimplemented). An unknown `@mention` target is refused before any
  download is attempted.
- **Largest available size**, `photo[-1]` — Telegram's own smallest-to-largest
  ordering for the `PhotoSize` array. This is the best *compressed* copy the
  bot ever sees: Telegram recompresses every "photo" upload itself, so full
  original quality isn't available through this path at all — a
  **"document"** upload preserves it instead, a different message shape,
  see [§2g](#2g-receiving-a-document-uncompressed). `mime_type` is always
  `image/jpeg` for the same reason — no content-sniffing needed.
- **`filename`** comes from Telegram's own `getFile` `file_path` (its
  basename, e.g. `file_123.jpg`), still run through the same basename
  validation `docs/CONTRACTS.md` specifies rather than trusted outright —
  falls back to a generated name if that ever fails.
- **Shares its download/validate/send mechanics with §2g's "document" path**
  (`_send_incoming_file_as_attachment`) — the only real difference between
  the two is *what's already known about the upload*: a photo has no name
  or MIME type of its own (both are supplied here, `image/jpeg` and a
  `file_path`-derived name), a document already carries both from Telegram.
- **A defensive size check against two different ceilings, not one applied
  twice.** `TELEGRAM_MAX_FILE_BYTES` (20MB) is what Telegram will let a bot
  download at all, checked against `PhotoSize`'s own reported `file_size`
  before downloading anything. `ATTACHMENT_MAX_BYTES` (10MB,
  `docs/CONTRACTS.md`'s decoded-content cap) is checked against the actual
  downloaded byte count — smaller than Telegram's own ceiling, so a photo
  between the two downloads fine and must still be refused here rather than
  left to the api's own `422`.
- **`blocked` presence is checked before any download work happens** — same
  as a text prompt, so a blocked agent doesn't cause a photo to be fetched
  for nothing.
- A **Telegram album** (several photos sent together) arrives as *separate*
  updates sharing a `media_group_id`, not one message with several photos —
  handled without any special casing, one `Attachment` envelope per photo.
  ⚠ Unlike a `Message`, **an `Attachment` is never combined into a burst**
  (`docs/CONTRACTS.md`) — an album reaching one agent shows up as N separate
  pastes, not one coalesced paste the way consecutive `Message`s would.

---

## 2f. Sending a File (the other direction)

`office send-file` lets an agent send this bot a real file — `ReplyPusher`
(§1) is what actually delivers it, since it already owns reading `telegram`'s
mailbox. Until this shipped, an `Attachment`-kind mailbox entry hit
`render_reply`, which only ever reads `payload.text` — absent on an
`Attachment` payload — so it silently rendered as `"<agent> sent a message"`
instead of the file ever reaching Telegram. `kind: "Attachment"` is now
checked before falling through to the ordinary text-reply path at all.

- **`content_base64` is decoded and forwarded via `sendDocument`**
  (`TelegramClient.send_document`, same multipart shape `send_voice` already
  used) — `filename` and `mime_type` come straight from the envelope
  payload, `caption` is prefixed with the sending agent (`from <agent>: ...`,
  or just `from <agent>` with none) the same way a text reply is prefixed
  with its source.
- **The full validation contract is re-enforced here, not just "is there
  something to send."** `docs/CONTRACTS.md` promises an api-type client
  "validates and decodes the same payload contract" the api door and the
  tmux opener do — the same defense-in-depth reasoning the opener's own
  re-check is built on: this envelope already passed the api door once in
  the normal flow, but a direct bus caller bypasses that door entirely and
  would otherwise reach this code with no real validation at all. Checked,
  reusing the same functions/constants the send side
  (`handle_photo_message`) already defined rather than a second copy of the
  rules:
  - `filename` against the spec's basename rules (`_valid_attachment_filename`)
  - `mime_type` against the spec's grammar and length (`_valid_attachment_mime_type`)
    — a missing one is **rejected**, not defaulted to
    `application/octet-stream`; it's one of the three required fields
  - `caption`, when present, against the 65,536-UTF-8-byte cap
    (`ATTACHMENT_MAX_CAPTION_BYTES`)
  - the decoded byte count against `ATTACHMENT_MAX_BYTES` (10MB) — the
    same cap the send side checks, here applied to what an agent sent in
  - **the payload's closed shape** (`ATTACHMENT_ALLOWED_PAYLOAD_KEYS`) — an
    envelope carrying any field beyond `filename`/`mime_type`/
    `content_base64`/`caption` is rejected outright, matching "no other
    field is accepted"
- **A failure is reported back to the chat, never silently dropped** — any
  rejection above, a `content_base64` that fails strict decoding, or
  Telegram's own `sendDocument` call failing (file too large, rejected
  type, network error) all produce a plain-text error message in the chat,
  mirroring the receiving side's rule (`handle_photo_message`) rather than
  leaving the operator to wonder why nothing arrived.
- **Telegram's own caption limit (1024 chars) is enforced client-side**,
  same truncation `send_voice` already applies — smaller than the bus's own
  65,536-UTF-8-byte cap (`docs/CONTRACTS.md`), so a long caption that's
  perfectly valid on the bus still gets cut for Telegram specifically.

---

## 2g. Receiving a Document (Uncompressed)

Telegram's normal "photo" picker always recompresses before this bot ever
sees it — Telegram's own behavior, not something fixable here. Sending as a
**document** instead (send as file, not as photo) skips that recompression,
so this is the path for anyone who actually needs the original bytes —
`message.document` is a single object with its own `file_id`/`file_name`/
`mime_type`, not an array of `PhotoSize` like `message.photo`, and not
always JPEG.

- **Shares every mechanic beyond that with [§2e's photo
  path](#2e-receiving-a-photo)** (`_send_incoming_file_as_attachment`) —
  `@mention` routing, `blocked` presence, both size ceilings
  (`TELEGRAM_MAX_FILE_BYTES` for the download, `ATTACHMENT_MAX_BYTES` for
  what the bus accepts), and sending the real `Attachment` envelope are all
  the identical code path a photo already used, not a second copy of it.
- **`filename` and `mime_type` come from Telegram directly** (`file_name`,
  `mime_type`) instead of being derived or hardcoded the way a photo's are
  — still run through the same validation as any other Attachment
  (`_valid_attachment_filename`/`_valid_attachment_mime_type`) rather than
  trusted outright, since Telegram's own metadata isn't guaranteed to be
  spec-shaped (e.g. a `mime_type` with a `; charset=...` parameter, which
  the closed grammar in `docs/CONTRACTS.md` doesn't allow). An invalid
  `mime_type` falls back to `application/octet-stream` rather than
  refusing the file outright — the content is still fine even if the
  reported type isn't — and `mime_type` is genuinely optional in Telegram's
  own API, so a missing one gets the same fallback. An invalid `file_name`
  falls back to a generated name, same idea as a photo's fallback but with
  no extension assumed (a document could be anything).

---

## 2h. `/run` — an Allowlisted Exception to "`Command` Is Not Exposed"

`/run <agent> <command>` sends a `Command`-kind envelope instead of the
`Message`-kind shorthand every other text path uses: `command_opener` pastes
the text raw, with no `[message from telegram]` wrapper, so a native CLI
slash command (e.g. Claude Code's `/clear`) is interpreted by the underlying
CLI instead of read as chat text saying "/clear". One-off, same as
[`@mention`](#2a-menu-a-pinned-keyboard-not-a-one-off-message) —
`chat_target_agent` is never touched by this.

⚠ **This is a narrow, deliberate exception to §2a/`clients/web/SPEC.md`
§6's "`Command` is not exposed", not a reversal of it.** Full passthrough —
any text, executed bare in the pane — was the first shape this feature
took, and was rejected: it's unbounded remote execution from a phone with
no live view of the pane, exactly what that note was worried about, typed
command or not. What actually ships is bounded to a small, fixed allowlist
of native CLI slash commands (`RUN_ALLOWED_COMMANDS`/
`--run-allowed-commands`, default `/clear,/compact`), matched as an
**exact, whole-string** comparison — `/clear extra` is not `/clear` and is
refused, not passed through with an argument attached. Anything not on the
allowlist is refused with a plain-text reply naming what *is* allowed,
never silently dropped.

- **Global, not per-CLI or per-agent.** `GET /agents/{agent}` exposes no
  field for which CLI an agent runs (the same limitation
  `PANE_WATCH_CHROME_OVERRIDES`, §2d, exists for), and `claude`/`codex`/
  `agy`'s actual slash-command grammars are not something this client can
  verify without a live agent of each kind to check against. An operator
  running CLIs where `/clear`/`/compact` mean something else, or wanting a
  larger set, sets `RUN_ALLOWED_COMMANDS` instead of trusting an unverified
  per-CLI table here.
- **Single-line only, checked before the allowlist.** `command_opener`
  pastes the matched command with one trailing newline appended. An
  allowed command's own text carrying an embedded newline would submit it
  as one line and then paste a second, completely unvetted line of raw
  input right after — defeating the allowlist entirely. Refused with
  "`/run commands must be a single line.`" before the allowlist check even
  runs; none of the default entries need one, so this only ever fires on
  something added deliberately.
- **Presence-gated and activity-visible exactly like a normal prompt** — a
  `blocked` target agent is refused the same way `handle_user_prompt`
  refuses one, and the live activity progress message (§2c) starts the
  same way too, since a slash command can still trigger tool calls.
- **No per-operator restriction beyond the existing single
  `allowed_chat_id` gate** every command already goes through — there is
  no concept of distinct "operators" for one `chat_id` to be restricted
  relative to another yet. Revisit if/when that lands.

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
