# Telegram Bot Client (`clients/telegram/`)

A Telegram bot client that talks to an **h-flock** tenant over HTTP, allowing a user to communicate with the `architect` agent from Telegram.

---

## 1. Overview & Architecture

- **Participant Enrolment:** On startup, the bot enrols as a participant named `telegram` on the bus (`StartAgent` with `port_type: "api"`).
- **Single Progress Message Editing:** When a user sends a prompt, the bot creates a single Telegram progress message (`⏳ architect is working`) and edits it in place as tool execution events arrive from `/agents/architect/activity`.
- **Tool Call Summaries:** Tool executions are rendered as tool names (e.g. `⚙ Read`, `⚙ Bash`, `⚙ Edit`). Arguments are intentionally excluded. Edits are coalesced (max once every ~1.5 seconds) to respect Telegram API rate limits.
- **Typing Indicator:** Telegram's typing indicator is refreshed on a timer (~every 4s) while the agent presence state is `working`.
- **Separate Answer Delivery:** The answer from `architect` is retrieved from `/agents/telegram/messages` and posted as its own separate message.
- **`blocked` Visibility:** If `architect` is `blocked`, the bot immediately reports `"architect is not accepting messages right now"` rather than showing a perpetual typing indicator.
- **Cursor Persistence:** The cursor is saved to disk (`cursor.json`) after processing each message. On restart or reconnection, the saved cursor is passed to `GET /agents/telegram/messages?after=<cursor>` so the bot never replays old messages.
- **Built for Silence:** If no reply is produced, the bot does not time out or treat it as an error.

---

## 2. Configuration & Running

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `FLOCK_API_URL` | `http://localhost:8080` | Base URL of the h-flock REST API service |
| `FLOCK_API_TOKEN` | *required* | Bearer API token for authentication |
| `TELEGRAM_BOT_TOKEN` | *optional* | Telegram Bot API token (from @BotFather) |
| `CURSOR_FILE` | `cursor.json` | Path to store the persisted cursor |
| `TELEGRAM_CHAT_ID` | *optional* | Fixed chat for `--prompt`/`--status` one-shots and for live alert push (§2b) |
| `ALERTS_CURSOR_FILE` | derived from `CURSOR_FILE` | Path to store the alerts-stream cursor, kept separate from the mailbox cursor |
| `NO_ALERT_PUSH` | unset | Set to `1` to disable live alert push even when `TELEGRAM_CHAT_ID` is set |

### Running in Dry-Run Mode (Without Telegram Token)

When `TELEGRAM_BOT_TOKEN` is not supplied (or `--dry-run` is passed), the bot operates in **dry-run mode**, sending real envelopes and state requests to h-flock while printing all formatted Telegram message operations (`sendMessage`, `editMessageText`, `sendChatAction`) directly to stdout:

```bash
# Perform status check against real h-flock data
python3 clients/telegram/bot.py --api-token "$FLOCK_API_TOKEN" --status

# Send prompt to architect and watch progress edits / reply driven by real h-flock data
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
  --dry-run \
  --prompt "can you check the auth change?"
```

---

## 2a. Inline Menu

Sending `/menu` (alongside the existing `/status` and free-text prompts to
`--agent`) opens an inline-button menu with three actions, scoped to v1 rather
than full `office` CLI parity:

- **📋 Office overview** — presence and open ticket (`doing[0]`) for every
  `port_type: "tmux"` agent in the roster. Excludes api clients (like this bot
  itself) and `host`, the same filter the web console uses for lifecycle
  controls.
- **🎫 Add ticket** — pick an agent from inline buttons, then answer two plain
  text prompts (title, then description — send `-` to skip it). `/cancel`
  aborts at either prompt. Posts `AddTicket` to `POST /agents/{agent}/envelopes`.
- **⏯ Pause / resume agent** — pick an agent, then Pause or Resume. Posts
  `PauseAgent`/`ResumeAgent` to `POST /agents/host/envelopes`.

`StartAgent`/`StopAgent` (hire/retire) are out of scope for v1 as higher-risk,
destructive-by-default operations — see `clients/web/SPEC.md` §6a's confirm-by-
typing-the-name requirement for retire, which this menu does not implement.

While a chat has an open Add Ticket flow, its next plain text message is
consumed as the flow's answer rather than sent to `--agent` as a prompt.

Try it without a bot token: `python3 clients/telegram/bot.py --api-token "$FLOCK_API_TOKEN" --menu`.

---

## 2b. Alerts

**🔔 Alerts** (added to the same inline menu) shows the tenant's recent
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
