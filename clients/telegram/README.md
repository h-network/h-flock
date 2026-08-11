# Telegram Bot Client (`clients/telegram/`)

A Telegram bot client that talks to an **h-flock** tenant over HTTP, allowing a user to communicate with the `architect` agent from Telegram.

---

## 1. Overview & Architecture

- **Participant Enrolment:** On startup, the bot enrols as a participant named `telegram` on the bus (`StartAgent` with `vab: "api"`).
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

## 3. Documentation Gaps in `docs/API.md`

Built strictly against [`docs/API.md`](../../docs/API.md). The following gaps and ambiguities were encountered:

1. **Presence `blocked` State Omission in §5 Header**:
   Section 5 under `GET /agents/{agent}` (line 248) states: *"returns queue depths and presence status (working, idle, unknown)"*. It omitted `blocked` as a possible presence state in that section, even though `blocked` is a critical presence state documented in `CONTRACTS.md` and `HLD.md`.

2. **Re-enrolment Idempotency Behavior**:
   Sections 3 and 5 document `POST /agents/host/envelopes` with `StartAgent` and `vab: "api"` for enrolling application clients, but do not state whether re-enrolling an already enrolled client (e.g. upon client restart) is idempotent or what HTTP status/body is returned.

3. **Task Board Ticket Schema Variability**:
   Section 5 gives an example response for `GET /agents/{agent}/board` with task objects containing `id`, `title`, `description`, `created_by`, `status`, `created_ts`, and `priority`. However, for legacy tasks or raw string items, `API.md` does not explain whether task items can be non-dict objects or strings.

4. **SSE Event Stream Reconnection (Header vs Query Parameter)**:
   Section 4 documents both `?after=<cursor>` (query parameter) and `Last-Event-ID` (HTTP header) for resuming SSE event streams. It does not specify precedence if both are present or note browser `EventSource` constraints (where custom headers cannot be set).

5. **Activity Feed Event Kinds & Schema**:
   Section 5 notes that `tool` events carry a `tool` string (e.g. `"tool": "Bash"`), but does not explicitly enumerate all valid values for `kind` or state whether `tool` is null/absent for non-tool event kinds (`input`, `output`).

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
