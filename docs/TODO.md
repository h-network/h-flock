# Parked

Things decided-but-not-done, so they live somewhere other than a chat log.

> **Reconciled against code at `main` on 2026-08-21.** ⚠ **The previous
> reconciliation was 2026-08-14, and 69 commits landed in between** — v3 and v4
> wire, the port rename, the policy check, the watchdog split, the opt-in door.
> **Five rows in "Open right now" described work that was already done**, and the
> citation gate could not catch a single one of them: every path they named still
> exists, so the file passed while being wrong. ⚠ **A row here is a claim about
> the tree. Re-read it against the tree before you trust it.**

## Open right now

⚠ **`clients/` is finished.** The Telegram bot and the browser console stay as
**demos** — two working examples someone can run on day one. No further client
development happens in this repository; the framework is the product.

| | |
|---|---|
| **profile logins** | one interactive login per account. Not buildable — a person has to do it. ⚠ **Checked: nobody has solved this.** NVIDIA OpenShell's own tutorial says you authenticate with your own account in a browser, and trust the workspace when prompted |
| **local model: long-context behaviour unknown** | every test was a short turn against a 65k window. Nothing says what a local agent does when it fills |
| **security: what is left after build 36** | ⚠ **The boundaries are done** — TLS on both doors with a refusal to serve a non-loopback bind without it, `source` stamped from its egress queue, and a tenant that will not start with a widened Redis bind and no password. What remains is **CORS and per-client tokens** on the api door. ⚠ **Nothing here isolates agents from each other**, deliberately: h-flock is a development office, agents are colleagues who were hired. HMAC envelopes, a brokered `office`, one OS user per window — that is a service executing work for callers it does not trust, a different product |
| **the console cannot reach TLS doors** ⚠ *found by testing TLS, not by reading* | `clients/web/server.py` proxies for the browser, and its own client is plaintext-only: the WebSocket proxy opens a bare `socket.create_connection` (so terminals break against **any** cert, valid or not), and the REST proxy uses the default verifying context with no CA or insecure option. ⚠ **A supported configuration that breaks the shipped demo is a defect, not a missing feature** — but `clients/` is closed to development, so this is recorded rather than fixed. Roughly 30 lines in one file: ssl-wrap the socket, pass a context, add the option. Until then TLS belongs in a reverse proxy in front of loopback-published doors (`LLD-container` §3) |
| ~~**`setup.sh` cannot choose a CLI without multiple accounts**~~ **— FIXED 2026-08-23** | ⚠ **Accounts and frameworks are independent questions and are now asked independently.** *"Default CLI"* and *"any agents differing"* moved out of the accounts branch, so a single-account tenant can pick codex or agy, and the account question is asked only when there is more than one to choose from. Verified: one account, both agents `codex`; and one account, claude default with a single `agy` exception. ⚠ **`accept.sh` drives these prompts POSITIONALLY** — its answers moved in step, and the mapping is now listed one per line above the `printf` so the next person adding a prompt sees what they are shifting. **Hit twice in two days** standing up offices that wanted codex and agy, which is what made it worth fixing rather than documenting. The original: | The "Default CLI (claude/codex/agy)" prompt lives **inside** the multi-account branch, so a single-account install silently gets claude whatever you wanted. Measured while standing up a codex office: three agents came up on claude, and the only way through was `AGENT_CLIS=` written into `container/.env` by hand |
| **seeded credentials do not survive `--force-recreate`** | They live in the container filesystem by design — never baked, never a volume — so recreating the container deletes them. ⚠ **And nothing notices:** `seed-home check` reports "logged in" because it tests the *host's* staging copy, so a tenant whose agents are all sitting at a login prompt reports healthy and authenticated. Measured: `auth.json` absent inside, three codex agents stuck on a sign-in screen, doorbell delivered into the void |
| **`office swap <agent> --cli <x>`** ⚠ *operator's idea, and mostly already built* | The CLI is a Redis value (`agent:<name>:launch`) and `tmuxhost` rebuilds a missing window from it, so replacing the process while keeping the name, board, queues and workdir needs no new machinery. ⚠ **Not stop-then-start:** `StopAgent` destroys an api client's unread mailbox (audit F6). Open questions: drain or discard the ingress, what presence reads during the gap, and what happens to a ticket already in `doing`. Costs the agent's memory, which is acceptable |
| **a local provider only works for claude** ⚠ *the fix now exists in the base image, unused* | ⚠ **Base gained `AGENT_PROVIDER_URL` / `_MODEL` / `_SMALL_MODEL` / `_TOKEN` on 2026-08-23**, and — the part that matters — **`startAgent codex` and `startAgent agy` with those set exit 3 rather than starting**. That is exactly the loud refusal this row asks for. ⚠ **h-flock does not use it**: `tmux/ops.py` still builds `ANTHROPIC_*` itself, so a codex agent with a provider still runs against the vendor while `setup.sh` prints `(local)` beside its name. **Delegating to base would close this row and delete code rather than add any.** The original: | `tmux/ops.py:258-291` sets `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN` and the three tier model variables. codex reads `OPENAI_BASE_URL` / its `config.toml`; agy supports no custom provider at all. **Assign a provider to a codex agent today and it runs against the vendor while `setup.sh` prints `(local)` beside its name** — cost and privacy both differ from what the operator was told. ⚠ **The cheap half is the refusal**: say it plainly at the prompt and log it when a non-claude agent carries an `provider`. The real fix is `OPENAI_BASE_URL` support for codex. Measured 2026-08-12 while planning to use a second vLLM |
| **`[message from x]` is an amateur sender field** ⚠ *the data half is fixed, the presentation is not* | ⚠ **v4 carries the sender as a field**: `source` is 63 fixed bytes in the header (`bus/envelope.py`), parsed by offset, never scanned for. So the *wire* half of this complaint is answered. ⚠ **The pane half is unchanged** — `port/openers.py:73` still pastes the literal `f"[message from {source}] {text}"`, so it still cannot be styled or filtered, still collides with a body containing the phrase, and **every test that counts deliveries still greps for it**. The remaining work is presentation and the tests, not the wire: Every delivery arrives as the literal text `[message from alice] …` pasted into the pane, so the sender is a **string inside the message body** rather than a field. It cannot be styled, filtered, parsed or trusted, it collides with message content that happens to contain the phrase, and every test in this repo counts deliveries by grepping for it — including the 100- and 4-agent benchmarks. ⚠ **Needs a proper sender presentation**, and a test that asserts the sender is carried as *data* rather than as decoration in the text |
| **a failed send leaves no trace anywhere** ⚠ *half fixed — (a) closed, (b) open* | ⚠ **(a) is closed.** `bus/doors.py:74` emits `send_refused` with the reason for every resolution or policy failure, and `bus/doors.py:86` emits `send_failed` when the egress write itself throws. Both are records on the bus, not prose in a pane. ⚠ **(b) is untouched** — an `office send` whose quoting breaks is still never invoked, so there is nothing to record; that needs the never-shell-parsed interface, and no build has taken it. The original, for the second half: Two depths, one symptom. **(a) `office send` runs and fails:** measured — `office: error: unknown destination agent 'operator'` was printed into a pane and recorded **nowhere** — not the bus, not the container log, not an alert. The command knew it had failed and told only the terminal. **(b) the shell eats the line before `office` runs:** `office send -a x "body"` puts prose on a command line, so broken quoting means our tool is never invoked at all — measured as `/bin/bash: line 14: VERIFIED-MODE: command not found` from an agent's own message. ⚠ **(a) is a missing log record; (b) needs an interface that is never shell-parsed** (`--stdin`, a file, a heredoc). ⚠ **Neither is an escalation** — the agent already has full Bash — and the model's quoting discipline is the proximate cause of (b), but the silence is ours |
| **not ours: the model and the CLI** ⚠ *recorded so nobody spends time on it* | Two failure causes seen in the same run belong to neither h-flock nor its docs. **A rejected tool name** (`Error: No such tool available: bash` when the CLI was started with `--tools Bash …`) is between the model and claude-code's registry. **An agent deciding a conversation is finished** despite a standing instruction is model behaviour. Both produce the same visible symptom as the row above — a turn that yields no envelope — which is why they are listed here: **do not go looking for an h-flock bug when you see it** |
| ~~**delivery verification says nothing under real load**~~ **— SHIPPED in build 81** | ⚠ **`input`, `output` or `tool` after the marker all count as alive now**, and the window is 120 s rather than 10 (`watchdog/verification.py`). An agent mid-turn emits tool calls and output for minutes; only counting *typing* is what produced the false negatives. ⚠ **Measured live on h-oracle: 0 of 40 flagged**, against 4 of 13 in build 74 and 1,180 of 1,285 on the three-hour run. ⚠ **It admits a false positive on purpose** — `output` can belong to the previous turn, so alive does not prove the paste was consumed. That is the safer error: a wedged process or a login prompt emits nothing at all. The original: | ⚠ **It lives in the watchdog now** — `watchdog/verification.py`, moved out of the fabric on 2026-08-17, so any reader chasing this in the switch or the port will not find it. ⚠ **Build 74 measured 4 unverified of 13 on a real Nemotron run** — better than 92%, still a third, and the four were healthy agents that simply did not type after the paste. **The defect is unchanged in kind**: the check cannot tell a wedged agent from a thinking one. The original run: A three-hour, four-agent run on a local model logged `delivery_unverified` for **1,180 of 1,285 deliveries** — "not confirmed by a later input activity event". Every one of them was received and acted on; we watched the agents reply. So the mechanism that exists to catch a wedged agent or a login prompt produced a verdict of "unverified" for almost everything, blocked nothing and retried nothing. ⚠ **A check that is wrong 92% of the time is worse than no check** — it trains everyone to ignore it. Either the activity feed does not report input for these agents, or the verification window is far too short for turns that take minutes |
| **the ~~five~~ six-record contract has holes under load** ⚠ *still open, but the numbers below are from a wire that no longer exists* | ⚠ **It is six stages, not five** — `kick_started` made it six in build 65 and `CONTRACTS` §4 already says so; this row did not. ⚠ **And the measurement predates v3 and v4**: it was taken on the old nested-JSON envelope, before the fixed header, before `send_refused`/`send_failed` existed to distinguish a lost record from one never emitted. **Re-measure on the current wire before treating the rates below as live** — they may have been fixed by the rewrite, and nobody has looked. Same run: **2 envelopes carried `opened` with no `received`** (1,283 of 1,285 complete), and **`sent` (1,279) was lower than `popped` (1,285)** — six envelopes entered the bus with no send record. Small rates, but `CONTRACTS` §3 states the five records as an invariant, not a tendency. ⚠ **Find out whether the records are lost or never emitted** before weakening the claim |
| ~~**the two adapters have one name between them**~~ **— SHIPPED** | ⚠ **Renamed by direction, as asked.** `port/send.py` is outbound, `port/deliver.py` is inbound, and the per-destination delivery routines are `port/openers.py`. **Neither `port/cli.py` nor `port/runner.py` exists any more**, so the description below names two files that are gone. Kept because it is the argument for the rename: `port/cli.py` is the **outbound** path — the `office` command an agent runs to put an envelope on the bus. `port/runner.py` is the **inbound** path — it blpops an ingress queue and hands the envelope to its destination, pasting into a tmux pane or writing an api client's mailbox. Both are adapters *for a destination*, and calling them both "the port" hides that they sit on opposite sides of the switch. ⚠ **Names should say which direction and for which destination**, because the design's whole claim is that adding a participant is adding one delivery routine — and you cannot see that from the current names |
| **a naming review** ⚠ *asked for by the operator* | Not just the adapters. The vocabulary has grown by accretion — `port`, `opener`, `door`, `runner`, `port_type`, `source`/`destination`, `egress`/`ingress`, `launch`, `board` — and some of it is precise while some is habit. ⚠ **Worth one pass across code and docs**, with the L2 model as the reference: a name that maps onto the analogy earns its place, and one that does not should say what it actually is |
| ~~**an ACL on `(source, destination)` in `send()`**~~ **— BUILT, and not in the shape below** | ⚠ **It exists**: `bus/policy.py` holds it as a Redis key beside the roster, and `bus/doors.py:61` enforces it at the single choke point exactly as argued. ⚠ **But it is not a src→dst allow-list.** It is an **import/export tag intersection** — `allows()` permits when policy is absent, otherwise requires the source's export tags to intersect the destination's import tags. That is a different object with different failure modes: a tag added to one participant silently widens every peer that shares it, which a pairwise list cannot do. ⚠ **A denied send now leaves a record** — `send_refused` at `bus/doors.py:74`, which is what the row below asked for. The original design, kept because the choke-point argument is why it went here: A src→dst allow-list as a Redis table beside the roster — **not** in `.env`, because policy is runtime state and should change without recreating the tenant. Enforce in `bus/doors.py:send()`: it is the **single choke point** onto the bus, with only two callers, `port/cli.py` (agents) and `api/app.py` (clients), so one check covers every path. Denied sends get a real error at the sender — non-zero exit in a pane, `422` from the door — **and a record**, which is what today's silent failures never produce. ⚠ **Keeps the switch policy-free**: `(source, destination)` are the source and destination addresses, so this is an L2 port ACL, not payload inspection. ⚠ **Limit, per `LLD-bus-and-switch:150`:** anything that writes an egress queue directly skips it — unreachable for agents since wave 2 removed their Redis credentials, but it is a guardrail against accidents, not a control against intent |
| **a `gateway` participant is the L3 switch** ⚠ *the model, extended* | `LLD-bus-and-switch` §3.2 already reserves a `gateway` port_type as deferred, and today an unresolvable name is dead-lettered — a switch with no default route. The operator's framing: **we built the switch and the ports; the gateway is layer 3.** It is the participant that reads what the switch will not (`kind`, payload), applies policy, resolves cross-tenant names and re-addresses — reached **by name, like any other participant**, exactly as hosts reach a default gateway by MAC. ⚠ **This is why h-flock has no policy in the switch and does not need one there** — a reviewer reading the absence as "doesn't want policy" has the layer wrong |
| **signed envelopes — to discuss, not decided** ⚠ *external feedback, 2026-08-12* | Proposal: add `kid` and `sig` (HMAC-SHA256) to the envelope, e.g. `{"kind":"MessageReceived","source":"telegram","destination":"policy","kid":"telegram-2026-08","sig":"…"}`. ⚠ **Do not read this as "sign everything".** Assessment so far, to be argued properly later: **(a) intra-tenant it buys nothing** — any key an agent can sign with it can also read, same user and `sudo`, so it creates no boundary that `HLD` §10 does not already deny; **(b) at the door it fixes a real gap that exists today** — there is one shared bearer token for all clients and `post_envelope` validates `as` only by roster membership, so any token holder can post as any enrolled client; `as` is a declaration, not a credential; **(c) at the `gateway` it will be required**, because cross-tenant is the first genuine boundary. ⚠ **The narrow version is "per-client keys at the door"** — the general version invites signing everything and gaining nothing. Rotation is already implied by the `kid` date suffix and would need an answer |
| **cross-tenant is designed twice, differently** ⚠ *design fork, needs a decision* | `LLD-bus-and-switch` §7 says cross-tenant routing is *"not a separate component — a branch in the switch"* that writes into the remote tenant's Redis. §3.2 and line 169 reserve a `gateway` **port_type** — a participant addressed by name, `pod` being *"a gateway, when routing between tenants"*. ⚠ **Only one can be built.** The switch-branch version spreads remote topology into the switch and has one tenant holding credentials for another's store, both of which the same document argues against elsewhere. The participant version keeps the switch's only decision local and puts the crossing where the trust boundary actually is. ⚠ **This is an architecture decision, not a doc fix** — recorded so it is made deliberately rather than by whoever implements first |
| ~~**restart durability is one flag, if we want it**~~ **— DONE, and the design question was answered** | Redis runs `--appendonly yes --appendfsync everysec` (`container/entrypoint.sh`). ⚠ **The row's real question was *which keys should survive*, and the answer is in `purge_transport`**: boards and streams persist through AOF, while ingress, egress, dead and the delivering lock are purged at boot. So work survives a restart and in-flight transport does not — which is what keeps at-most-once true across a crash, since a replayed ingress entry would re-deliver an envelope whose port had already pasted it. The original: | Redis runs `--save '' --appendonly no --dir /tmp` by design. `docker restart` keeps the container filesystem, so `--appendonly yes` with a dir inside the container would make boards, roster and queues survive the restart `seed-home.sh` actively recommends — the finding from the four-agent run. Dataset was **1.62 MB** after 1,285 messages, so cost is negligible. ⚠ **The design question is not "can we" but "which keys should survive"**: boards are work and should; a half-delivered ingress replayed after a crash could re-deliver an envelope whose port already pasted it, which is the duplicate execution at-most-once exists to prevent |
| ~~**envelopes have no TTL or hop count**~~ **— HALF SHIPPED in build 73** | ⚠ **The TTL half is built.** `bus/envelope.py:127` carries `ttl` (default 16) and `hops` in the v4 header, and the switch dead-letters at `switch/service.py:151` with reason `"ttl expired at forward"`. ⚠ **The broadcast half is still open, and the ACL does not cover it**: `bus/doors.py:61` skips the policy check when `destination` is `all`, so a broadcast storm still has nothing in front of it. The original entry, kept for the reasoning: Four agents replied to each other for three hours and 1,252 envelopes with nothing in the envelope saying how many times it had been forwarded. It stopped because a human typed a line. In the networking model this is a packet with no TTL: a conversation loop cannot die on its own. ⚠ **Related: no loop detection and no rate limit on `destination: all`** — a broadcast storm has nothing to stop it. An envelope field, a decrement at forward and a dead-letter at zero is the whole mechanism |
| **an alert you can clear** ⚠ *asked for by the operator* | Alerts are an append-only stream with no acknowledgement. Clearing must be keyed by **cursor** — one instance — so it can never become "mute this kind". Spec: `BUILD-38-durable` §1 |
| **credential alerts never clear** | Measured: `status=absent` raised at `01:00:42Z`, login completed at `01:07Z`, nothing ever retracted it, so the console correctly rendered a fact that had been false for an hour. ⚠ **It was only ever tested firing.** `BUILD-38-durable` §2 |
| **the permission mode lives only in argv** ⚠ *probably closed, and the trigger was never reproduced* | ⚠ **The base image now ships `skipDangerousModePermissionPrompt: true` in `~/.claude/settings.json`**, and a file survives the CLI self-re-exec that argv does not — which is the exact mechanism this row describes. h-flock inherits it since 2026-08-23 and no longer ships its own copy. ⚠ **Not marked closed**, because the original trigger was never reproduced (*"a forced resize does not reproduce it"*), so there is nothing to test the fix against. If an agent is seen asking for permission again, this row is why. The original: | A hired agent starts as `claude --dangerously-skip-permissions …` (verified at +4s/+8s/+12s) and was later seen as bare `claude` carrying `CLAUDE_CODE_RELAUNCH_*`: the CLI re-executed itself and the flag went with it, leaving the agent asking for permission. ⚠ **The trigger is unknown** — a forced resize does not reproduce it. `BUILD-38-durable` §3 |
| **console conversation needs `--audit-log`** | Outbound messages are rebuilt from the audit log, so without that flag every refresh looks like data loss. Agent replies survive; yours do not. `BUILD-38-durable` §4, and a failing flow in `clients/web/flow-check.py` |
| **no acceptance seat** | Everything above was found by an operator, not by a lane or by me. Lanes have no Docker and cannot run what they build; the architect writes the specs and then checks his own work. ⚠ **`flow-check.py` is the floor, not the answer** — a script catches regressions, it does not notice an agent quietly asking for permission |
| ~~**nothing says what a run costs**~~ **— SHIPPED in build 82** | ⚠ **`office usage` exists**, reading the `usage` records the watchdog emits from the CLI session files `ActivityTailer` already tails. Four token buckets, longest-prefix pricing from `container/config/pricing.json`, and a model with no entry reads `unpriced` rather than `0.00`. ⚠ **Spend also joins to a conversation**: the first usage record after a delivery marker carries that envelope's `stream_id` and `correlation_id` — measured live, 18 of 27 attributed. ⚠ **What is still open**: attribution loss is silent, because `delivery.markers` is bounded at 500 and a trimmed marker produces an unattributed record with no signal. The original entry: | h-office carried `usage.py` and a `pricing.json` and could answer "what did that sprint cost". h-flock has **no cost surface at all** — not per agent, not per tenant, not per run. ⚠ **It matters most exactly where h-flock is strongest**: four agents on a vendor CLI for five hours is the normal shape of a build here, and the operator finds out from a billing page afterwards. A local provider makes it free and the number uninteresting; a vendor one makes it the first question. **Port shape is known and small** — the h-office files are the reference |
| **every sign-off so far was signed by its own author** ⚠ *no longer true — and the arrangement is still not set* | ⚠ **Builds 80, 81 and 82 all carry `author of the change? NO`** — the first independent signatures in this repository. `tmux` refused build 82 six times, each at a real locus. ⚠ **But nothing makes that happen.** It exists because I wrote *"VERIFIED BY is not you"* into three build specs by hand and withheld merges; no agent is told to review anyone and no check fails. ⚠ **And it does NOT belong in the framework** — h-flock sets an office up, it does not direct how agents work. This is an operator arrangement, recorded here so it is chosen rather than drifted into. The original: | `TEST-SIGNOFF` ends with `VERIFIED BY <lane> — author of the change? YES\|NO`, and **every gate in this repository to date says `architect` and `YES`**. The field was added because BUILD 77 shipped two defects that `api` found on first independent read. ⚠ **A field that records the problem without preventing it is not a control.** The three lanes independently proposed a **rotating attacker chosen before implementation** rather than a permanent adversary seat; nothing has been set up to do that. **The arrangement half is the operator's to set, not mine** |
| **`CLAUDE_CODE_OAUTH_TOKEN`** ⚠ *plumbing built 2026-08-23; whether the token AUTHENTICATES is still unproven* | ⚠ **Built**: `setup.sh` asks per account with `read -rsp` so nothing is echoed, stores `CLAUDE_OAUTH_TOKEN_<PROFILE>` in `container/.env`, and preserves it across re-runs the way `API_TOKEN` already was — so re-running setup to add an agent no longer deletes it. `window_env` injects only the token matching that agent's profile, so two accounts never receive each other's credential and the profile decides both config dir and credential. Absent stays absent rather than becoming an empty string, which the CLI would read as a credential that fails. ⚠ **NOT verified**: nobody has confirmed the CLI accepts the token at all, nor what happens when a profile has BOTH a token and a seeded `.credentials.json` — that precedence decides whether a token replaces a login or only fills an absence, and it is one sentence of help text either way. ⚠ **Transport is the operator's problem and stays one**: however it arrives, the token rests in `.env` (mode 600, never in the image) and is readable from `/proc/<pid>/environ` by any agent, same as `API_TOKEN`. `scp` beats typing it; a silent prompt beats shell history | ⚠ **Unknown to h-flock today**: zero references in code or docs. Auth is a *file* — `seed-home.sh` `docker cp`s `.claude/.credentials.json`, `.codex/auth.json` and agy's OAuth token into a running tenant. ⚠ **A token turns that into configuration**, which closes *seeded credentials do not survive `--force-recreate`* outright and turns *profile logins* from one interactive browser login per account per rebuild into minting a token once. **Four integration points**: ask per account in `setup.sh`'s existing accounts branch; store per **profile** in Redis beside `provider` (`tmuxhost/host.py:53`) and **not** in `.env`, because `.env` reaches the tmux server and therefore every pane; inject per window where `ANTHROPIC_AUTH_TOKEN` already is (`tmux/ops.py:279`); and leave the file path untouched so both work. ⚠ **Two things bite.** `watchdog/service.py:264` tests for `.credentials.json`, so a token-authenticated agent alerts `status: absent` **forever** — and credential alerts never clear. And **precedence must be decided and written down**: `ops.py` already carries the scar *"a previous subscription's `ANTHROPIC_*` wins over what we set here"*. ⚠ **It buys correctness, not isolation** — every agent is uid `ubuntu`, so a per-window env var is readable from `/proc/<pid>/environ` by any peer. It guarantees the right agent uses the right account; it does not keep account A's token from agent B |
| **a hire leaves no record of whether it worked** ⚠ *found while trying to answer exactly that, 2026-08-23* | `src/flock/control/openers.py` contains **no `log_record` or `emit` call at all**. `StartAgent`, `StopAgent`, `PauseAgent` and `ResumeAgent` take custody and never say what they did, so an envelope to `host` shows the six transport stages ending in `opened` and then nothing. ⚠ **Measured**: two envelopes `architect -> host`, all six stages clean, and the only way to learn whether an agent had been created was to attach to a pane. ⚠ **`AddTicket` already does this right** — `port/openers.py:211` emits `board_write_confirmed` — so the pattern exists and the control kinds are the exception. ⚠ **And `LLD-bus-and-switch` states the contract as *"each component records that it took custody and what it then did"***, which these do not. A confirmation per control kind, naming the agent and the outcome, is the whole fix |
| ~~**codex usage records are invented for sessions that did no work**~~ **— FIXED 2026-08-23, and it was worse than recorded** | ⚠ **Real codex work was recorded as zeros too, not just idle sessions.** A live agent logged **28,908 input and 22,016 cached tokens** and h-flock recorded nothing. `_codex_usage` matched the right record and then read `payload` directly — the counts are two levels down at `payload.info.last_token_usage`. ⚠ **The test was the reason it shipped**: it constructed a flat `{"type":"token_count","payload":{"input_tokens":…}}`, a shape codex has never written, and passed. It now carries a record captured from a live session. ⚠ **`last_token_usage`, never `total`** — total is cumulative, so summing it across records gave 43,281 for a session that used 28,908. A record with no tokens is no longer a usage record at all, which is the original finding. Both properties have controls proven to fail. The original: | `_codex_usage` (`watchdog/activity.py`) matches on the SHAPE of a record, not on whether it carries anything: `elif "input_tokens" in payload` accepts a `token_count` event whose value is zero. ⚠ **Measured**: an agent that logged into codex and was then retired — no work at all — produced **9 usage records**, every one `{model: "unknown", input: 0, cache_read: 0, cache_write: 0, output: 0}`. ⚠ **So `unknown` in a cost table means three different things** — ran and cost nothing, ran and we failed to identify the model, or never ran — and the reader cannot tell which. Same defect class as `delivery_unverified` before build 81 and the `usage.unattributed` counter review made us delete: **a signal that fires on the normal case cannot surface the abnormal one.** ⚠ **Do not fix blind**: nobody has yet seen a codex record from real work, so 9 empty ones is a poor basis for a filter |
| **cost-per-conversation undercounts by roughly the turns-per-delivery ratio** ⚠ *the spec's model was wrong, not the code* | Build 82 attributes **the first usage record after a delivery marker** to that envelope. ⚠ **Measured on a real session**: 237 usage records, 32 deliveries, and every attributed delivery got **exactly one** usage record — 9 of 237, 3%. On a short Nemotron run it read 18 of 27, 67%. **The difference is turns per delivery**: one message can trigger twenty-five turns of work, and twenty-four of them carry no `stream_id`. ⚠ **The implementation does what BUILD-82 §3 says; §3 assumed one turn per delivery and real agent work is not shaped that way.** Attributing every usage record until the *next* marker is the obvious answer and is not obviously right — an agent working on its own initiative between messages would be charged to whichever message came last |
| ~~**`accept.sh` exits 0 when it skipped the console flows**~~ **— FIXED 2026-08-23** | ⚠ **`1+` means a step FAILED, `100` means everything that ran passed and something did NOT run, `0` means complete and clean.** A caller can tell *broken* from *incomplete* without parsing prose. Verified across all four combinations, including that a real failure still outranks a skip. The script's own comment said *"Never let a skip read as a pass"*, which was true of its output and false of its status — and status is what a person glances at. The original: | `container/accept.sh:222` is `exit "$FAILED"`, and a skip only appends to `$SKIPPED`. So a run that never opened a browser prints `⚠ NOT CHECKED: console-flows` **and returns 0**. ⚠ **The script's own comment says *"Never let a skip read as a pass"*** — which is true of its output and false of its status, and status is what a person glances at and what any wrapper reads. ⚠ **This is the same defect the whole of 2026-08-22 was spent on**: `tmux` refused build 82 partly because a `pytest.skip` let the gate exclude a property, and the fix there was to fail rather than skip. The fix here is one line — `exit $(( FAILED + (${#SKIPPED} > 0) ))` or equivalent — but it changes what acceptance *returns*, so it is recorded rather than done in a doc sweep |
| ~~**25 build docs quote a throughput with no host named**~~ **— CLOSED 2026-08-22** | Six already named a host; 19 now carry a banner saying they do not and that the spread between our two hosts is 130×. No figure was edited and no history rewritten. `DRIFT` §4 has the re-check. The original: | Figures measured on the 4-vCPU lab are quoted in `BUILD-*.md` without saying so, and the same scripts read **6.5/s on the lab and 853/s on h-oracle** — a 130× spread. ⚠ **Any of those numbers, lifted into a summary, is wrong by two orders of magnitude and looks perfectly plausible.** `BUILD-CONVENTION` 3.0 fixed the convention going forward; **the 25 documents written before it were never back-filled** |
| ~~**`accept.sh` needs a playwright venv on the lab**~~ **— CLOSED 2026-08-23** | `BUILD-CONVENTION` §3.0b names it, gives the invocation, says the venv already exists at `~/pw-venv` on the lab, and explains why a new host must create one *before believing a green acceptance*. The script itself has said what it did not check since 2026-08-20, and now exits 100 rather than 0 when it skips. The original: | ⚠ **`accept.sh` handles it and says so loudly**: `accept.sh:190` tests for playwright, and without it prints *"console FLOWS WERE NOT CHECKED"* and *"This run is incomplete"* rather than staying silent. ⚠ **But `BUILD-CONVENTION` still never mentions it**, so an operator standing up a new lab host has no way to know. ⚠ **And see the row below** — the warning is prose, not status. The original: | The console flows in acceptance need `PATH=~/pw-venv/bin:$PATH` on `h-lab@172.16.0.14` or they skip — and **a skip reads as green**. This is why acceptance ran "clean" for weeks without ever exercising the console. ⚠ **Belongs in `BUILD-CONVENTION`**, next to the two hosts |
| ~~**ollama**~~ **— closed, and the old entry was wrong** | Run end to end 2026-08-11 against `ollama/ollama` serving `gpt-oss:20b`: `/v1/messages` answers with a proper message object, an agent made a tool call, and its `office send` arrived in a colleague's terminal. ⚠ **This entry previously asserted that ollama does not serve the Anthropic Messages API and needs a translating proxy. It serves it directly.** The assertion was never measured — it was reasoning wearing the clothes of a finding, and it survived several doc sweeps because nobody re-read it as a claim |

⚠ **macOS, 2026-08-11:** installs and runs on a stock MacBook (Apple Silicon,
Docker Desktop) — plumbing check 25/25, simulator 19/19. `setup.sh` used
`declare -A`, which is a syntax error on the bash 3.2 macOS ships, so it died on
its first prompt; the maps are now bash-3 compatible. LibreSSL 3.3.6 accepts
`-addext`, so the self-signed path works there too.

⚠ **TLS run end to end, 2026-08-11:** a tenant with a real certificate serves
TLS 1.3 on both doors and passes the plumbing check 25/25, and the failure
simulator 19/19. Two defects only that run could find: the healthcheck probed
plain HTTP at an HTTPS door, so a working TLS tenant sat unhealthy forever; and
both checker scripts had the scheme baked in as a constant.

⚠ **The "TLS breaks sim-blocked" item is closed, and it was never about TLS.**
`sim-blocked.sh` sourced `container/.env` over an exported `TENANT`, so running
it against any tenant other than the one in that file polled the wrong tmux
session. The ready poll saw no window and failed; the gone poll saw no window
and passed — which is exactly the flaky, paired signature that made it look
environmental. `tmux` answered `can't find session: hq` on every call, into a
stream nothing was reading. **The same bug was fixed in `plumbing-check.sh` days
earlier and missed here**, and the lesson is that one: a fix to a shared pattern
is not done until every copy of the pattern has it.

⚠ **Verified by running it, 2026-08-11:** plumbing check 25/25 and the failure
simulator 19/19 against a real tenant, after a from-scratch image build. The
same run found that build 36's TLS guard refused every container (a bind is not
an exposure — `LLD-container` §3.1), and two defects in the check itself: it
hardcoded session `hq`, and sourcing `container/.env` overwrote an exported
`POD`/`TENANT`, so its documented override checked the wrong tenant — **fixed;
`plumbing-check.sh:29-36` preserves them now**.

**Recently closed:** the installer's TLS answer (build 37 — create, copy, start; host path is not the container path), macOS support, the terminals view ignoring a hire, port security on `source` and TLS on both doors (build 36 — each forced on the lab, not reasoned about), the stranded window (a `__init__` placeholder holds the
session open now), silent trust and guide failures (recorded, still never
raising), the console audit scope (renamed to Operator Action Log), the terminal view (the console has a full workspace), the
five doc drifts (audit 06), AddTicket delivery without a window (build 35),
credential staleness (a decision, not a fix),
credential alerting, `delivery_unjudged`, and the octal/snapshot/telemetry
defects a night of live running turned up.

⚠ **This index has been wrong four times in one day.** Each time a build closed
an item and nobody told this file — the correction arrived in a later audit
rather than with the work. **A build that closes an item marks it in the same
commit.** Do not leave it for a sweep.

## The independent audits

Two offices of three agents each, same snapshot (`4bc702b`), same brief, no
remote and no ssh key — their output is a document, not a change.

- **`auditClaude`** (3 claude agents) — done: 2,094 lines across three documents,
  exported to the branch of that name and to `~/audit-export/docs/`. ⚠ **Two
  findings spot-checked and confirmed already:** `host.py:201` calls `.append()`
  on the `set` that `ops.py:56` returns, so the `__init__` placeholder path
  raises; and `entrypoint.sh:112` exports `REDIS_URL` with the password inline
  and never unsets it, so the Redis password reaches every agent window — the
  one thing `API_TOKEN` is explicitly unset at line 27 to prevent.
- **`auditCodex`** (3 codex agents) — running. Briefed directly rather than
  through the claude office, so they cannot inherit its conclusions.

**The consolidated list is [`AUDIT.md`](AUDIT.md)** — 50 findings, ranked by
consequence, each with the evidence its auditor cited and a status column. Work
it top down.

⚠ **Neither audit has been triaged.** A finding is a claim until it is checked
against the tree, and a previous auditor on this project cited files that did
not exist.

## Everything below is closed

⚠ **A struck-through or `SHIPPED` heading is a record of the time it was
written**, kept because the reasoning is why the fix went the way it did. Those
sections name commands that no longer exist — `sendMessage`, `sendBroadcast`,
`peers` — and that is deliberate: they are what the problem looked like then. The
current surface is one `office` command (`CONTRACTS` §5). Everything **not**
struck through is present tense and should be true today.

Each says *why* it is parked — an item with no reason is either work or noise.

Deferred *design* questions stay in each LLD's §7. This is the operational list.

## Agents in windows

⚠ **This was wrong, and build 15 disproved it by testing rather than reading.**
Both have seedable state: codex trusts a directory via `[projects."<cwd>"]
trust_level = "trusted"` in `config.toml`, and agy is suppressed entirely by
`cache/onboarding.json`. Both are seeded now and both CLIs start unattended.

The original entry, kept because the reasoning is why it went unchecked so long:

**Onboarding for `codex` and `agy` — checked, and there is nothing to seed.**
Run headless in a fresh container, both go **straight to a login prompt**:
codex offers "Sign in with ChatGPT / Device Code / API key", agy offers "Google
OAuth / Cloud project". Neither has a pre-login gate.

`claude` is the odd one out — a theme picker *and* a per-directory trust dialog
before login, which is why it alone needed `hasCompletedOnboarding` and
`hasTrustDialogAccepted` seeded.

Their post-login approval gates are already covered: `startAgent` passes
`--dangerously-bypass-approvals-and-sandbox` to codex and
`--dangerously-skip-permissions` to agy.

So all three need only **credentials**, which
[`container/seed-home.sh`](../container/seed-home.sh) now handles.

**A delivery arriving while a modal is open is lost — every CLI, not just agy.**

Measured on 2026-08-09 against a live tenant. A `/model` picker was opened in an
agy window and a normal `office send` was delivered into it:

- **the message vanished** — no trace in 2000 lines of scrollback, no reply to
  the sender, and the bus logged `opened` and considered it delivered
- **the Enter selected the highlighted row.** Benign here, because the highlight
  sat on the current model. It need not have been

⚠ **Originally filed as an agy problem, and that was too narrow.** agy surfaces
it often because its pickers are everywhere, but the mechanism — a modal has
focus, so the paste goes nowhere and the Enter actions the modal — is true of
claude and codex too. Any CLI, any modal.

⚠ **`Escape` before pasting was tested and rejected. Do not re-propose it.**
It does close a picker, and a message delivered straight after one landed
correctly. But sending it to an agent that is *mid-generation* **aborts the
work** — verified: the pane showed `Interrupted · What should Antigravity CLI do
instead?`. Delivering to a busy agent is the normal case and a picker collision
is rare, so the mitigation destroys real work far more often than it saves a
message. The trade runs the wrong way.

⚠ **Built in build 19, and it does not catch this case.** Measured: with a modal
open the message was consumed and never seen, yet claude wrote `input` records
anyway, so verify passed it. Verify catches an unsubmitted paste, not a modal
swallow. The modal hole is still open.

→ **What would actually help is `verify`** — confirm the text landed after
delivering, and re-deliver when it did not. Already parked above as the missing
step h-office added after measuring ~1 delivery in 10 left unsubmitted. It
catches the silent loss. It does **not** prevent the stray menu selection, and
nothing short of reading the screen before every paste would.

**Credentials and profiles — mechanism SHIPPED, logins outstanding.**
`container/seed-home.sh in|out|check` copies keys and credentials into a running
tenant and saves logins back out, and `setup.sh` asks for accounts and seeds each
one's config dirs. What remains is doing the interactive logins once.

⚠ **Last link missing:** nothing reads the `profile` key yet. `flock.tmuxhost`
reads `launch` for the CLI but does not turn `profile` into `CLAUDE_CONFIG_DIR` /
`CODEX_HOME` in the window environment — so accounts are seeded and selected but
not used.

The shape was taken from h-office, which solved it. The unit is the *account*, not the agent: a config dir is one
interactive login, so several agents share a profile and `default` is free.
`CLAUDE_CONFIG_DIR` / `CODEX_HOME` in the window env is the whole mechanism.

⚠ Our current onboarding seed writes `$HOME/.claude.json`, which covers the
**default profile only** — a second profile lands on the theme picker again
unless its own dir is seeded. Same bug h-office fixed in `4b88096`.

⚠ Still undecided: profile dirs must survive a rebuild, so they need a volume.
h-office gets that for free by being long-lived; we do not.

**The `startAgent` flip — and it was never about bash.** Found by watching a real
agent reply: `flock.tmux.create_window` launches the CLI **bare** —
`env AGENT_NAME=backend claude` — instead of `startAgent claude`. So the
permission flags are never applied and every command the agent runs stops on
*"This command requires approval"*.

`startAgent`'s own header says why that wrapper exists: *"Each CLI spells 'don't
stop to ask me' differently — claude `--dangerously-skip-permissions`, agy the
same, codex `--dangerously-bypass-approvals-and-sandbox`. Remembering which
belongs to which is the whole reason this wrapper exists."*

→ launch `startAgent <cli>` rather than `<cli>`. One line, and it covers all
three CLIs by construction rather than us tracking three sets of flags.

**The old framing.** Windows still run `bash -il`. `create_window` already
takes a command and `StartAgent` already passes one, so this is a default, not
work. Held deliberately until the two items above are solved — flipping first
just means every window stops on a prompt.

**Agent guide naming the lead is written once at window creation.**
If the lead is retired or re-ordered, existing agents' guides still name the previous lead until their windows are recreated. This is accepted because lead changes are rare, re-writing every guide on every roster change introduces unnecessary moving parts, and `office peers` reads the `<prefix>:lead` key live.

## Delivery

**~~The `verify` step~~ — SHIPPED in build 19.** Measured: 0 false positives
over 6 landed deliveries, and it catches the Enter-not-taken case below.

⚠ **The "misses a modal swallow" claim that stood here has been deleted**, along
with the same claim in `HLD` §8 — it came from a test asserting an absence that
passed whenever the switch had not yet judged. A modal was never separately
measured, so this file now claims nothing in either direction.

**Retry decision — CLOSED in build 30: surface, do not re-paste.** An unverified
verdict cannot tell an unsubmitted paste from one queued inside a stopped CLI or
picker. The simulator confirms the first text remains in both detected cases;
retrying while blocked cannot help, and retrying after a human clears it can
execute the instruction twice. We chose possible loss over possible duplication:
retain `blocked`, alert the human, and put the no-retry reason in the structured
`delivery_unverified` record. A human can resend when duplication is known safe.

The original entry, for the reasoning: `LLD-port-tmux` §4 says "verify,
optionally" and we took the option. h-office enables it by default after *"roughly one delivery in
ten left its message sitting in the destination's input box, marked delivered and
already popped off the queue"*. That is a silent loss path: `opened` is logged,
the envelope is gone from Redis, and the message was never submitted.
→ check the bottom rows for the message's tail after Enter, press it again if
still there. Costs one extra Enter that an empty prompt ignores.

## ~~An unknown agent reads as "exists, idle"~~ — SHIPPED in build 25

`404` for a name not in the roster, `200` for an enrolled agent holding nothing,
and `all` exempt because it is the broadcast address rather than a member. The
reasoning below is why it sat open as long as it did.

`GET /agents/<name>` returns **`200` with zero depths** for a name that is not
enrolled, and `404` only when the name breaks the segment rule. So a client
cannot tell "no such agent" from "an agent with an empty queue" — the two answers
are byte-identical.

Found by the api lane while verifying every call for [`API.md`](API.md), which is
the value of documenting against a running system rather than against the code.

⚠ **It is a trap for an app**, which will happily send to a typo'd name forever:
the `POST` is accepted, the envelope dead-letters somewhere the client never
sees, and the depths read zero throughout. Every layer answers truthfully and the
sum is misleading.

→ **Parked, not fixed**, because the fix is a decision rather than a patch:
`404` on an unenrolled name is the obvious answer, but the same handler serves
`host` and `api`, and boards deliberately return `200`/`[]` for an agent holding
nothing (`LLD-api` §2). Changing one without the other trades this inconsistency
for a worse one. Documented accurately in `API.md` in the meantime.

## ~~Visibility~~ — SHIPPED in build 20

**Presence** is `working` / `idle` / `unknown` on `GET /agents/{agent}` and in
`office status`, derived from the activity feed. **`blocked`** followed in build
28, from the switch's own delivery verdict. The **watchdog** shipped in build 27
and alerts a human, never an agent.

⚠ ~~One class remains open~~ — **closed in build 31, and it was never real.**
The claim was that a CLI at a login prompt records input it never acts on, so
verification passes. It came from a test asserting an *absence*, which passed
whenever the switch had not yet judged. With the verdict waited for
deterministically, claude and codex are **both caught**. Nothing here needs a
screen.

The original entry: **Presence.** No busy / idle / wedged / login-expired signal. h-office calls it
*"the single most expensive gap in a long session"* — every state looks
identical from outside. The signal is `window_activity` from one `list-windows`
call, which `LLD-port-tmux` §5 already names.

**Watchdog — both halves of the signal now exist.** It was blocked on boards, and
boards shipped in build 11. A ticket in `doing` carries `started_ts`, so "took
work and has not finished it" is answerable; window silence is the other half and
stops it crying wolf at an agent that is thinking. Nothing else blocks it.

**~~Boards~~ — SHIPPED in build 11.** Tickets, four columns, `office add`/`list`/`take`/`done`/`cancel`/`hold`/`delete`,
and an append-only history in `$TASK_RECORD`. The rule the design turned on held
all the way through: **the agent moves its own tasks, nothing infers them** — the
port knows an envelope was delivered and cannot know whether the agent read
it, started it, or disagreed with it.

⚠ It went further than that in the end: **nothing delivers a ticket at all.** A
board is pulled, so the one-`doing` rule is not enforced, it simply falls out.
The watchdog's evidence — a ticket sitting in `doing` with a `started_ts` — now
exists.

## ~~Broadcast strands envelopes on the fixed agents~~ — SHIPPED

**Fixed in build 08.** An unroutable port_type now dead-letters instead of returning
before popping, and port_type `api` has a delivery routine. `sendBroadcast` also
resolves its own recipients, so agent broadcasts never reach the fixed agents at
all. ⚠ Still undecided: whether `POST /agents/all/envelopes` *should* reach them
— an architect loose end, now cosmetic rather than a leak.

<details><summary>original</summary>

**Found by an agent during the first live run, then confirmed: `api` ingress was
34 and climbing, `host` dead-letters were 34.** Every `send all` reaches both,
because the switch fans out to `_agents() - {sender}` and the fixed agents are
roster rows like any other.

`host` handles it correctly — port_type `control`, no opener for `Message`,
dead-lettered and logged. Noisy, but visible.

`api` does not. port_type `api` dispatches to no delivery routine, so
`flock.port.runner` logs `port_type is 'api', not 'tmux'` and **returns before
popping**. The envelope is never consumed and never dead-lettered: it just
accumulates, one per broadcast, forever.

Two faults meeting, and they can be fixed independently:

1. **No `api` delivery routine.** The api-port opener — an envelope handed to
   a waiting HTTP client (`LLD-api` §7). Its absence should not be silent
   accumulation.
2. **An unroutable port_type should dead-letter, not return.** Whatever else is true,
   a port that cannot deliver must leave the envelope visible, the way an
   unknown `kind` already does. §4: *nothing disappears silently.*
3. **Whether broadcast should reach the fixed agents at all is still undecided.**
   The old switch excluded `api`; the current one includes it. Neither is written
   down — this is an architect loose end, noted at the time and not closed.

</details>

## ~~What belongs in a window's environment~~ — SHIPPED

**Done in build 08.** `AGENT_PEERS` removed, `OFFICE_TOOLS` added, the guide
names only the agent and is written once. Rule kept below because it decides
every future variable.

**The rule: static for the window's lifetime → environment. Derived from the
roster → a tool, never environment.**

A window's environment is frozen at creation. So anything that changes while the
office runs is wrong there, and goes stale silently.

| | |
|---|---|
| `AGENT_NAME` | env — fixed for this window |
| `POD`, `TENANT` | env — what `send` needs, fixed |
| `OFFICE_TOOLS=send,peers,…` | env — ships with the image, cannot go stale |
| **peers** | **a tool.** Changes the moment `StartAgent` adds one |

⚠ **`AGENT_PEERS` (build 06) breaks this and should be removed.** Add networking and
backend's `AGENT_PEERS` is wrong until her window is recreated — the exact
staleness the roster exists to prevent.

⚠ **The guide has the same bug.** `write_agent_guide` runs at window creation
only, so `/workdir/<agent>/AGENTS.md` ages the same way. Fix both together:
`flock.tmuxhost` already reconciles every `ROSTER_POLL_SECONDS` and already reads
the roster, so **rewrite the guide each pass**. A few hundred bytes, and it
leaves one source of truth instead of two that drift.

`OFFICE_TOOLS` also covers the reader who stops early: `echo $OFFICE_TOOLS` then
`--help` on each, with no exploring and no source to read.

## ~~Log records from agent tools never reach the log~~ — SHIPPED in build 20

`office` writes to a file the switch tails into stdout, so `sent` reaches the
log. **A delivered unicast envelope leaves five records, not four.** ⚠ A broadcast leaves three plus two per destination.

The original entry: ⚠ **`office` runs in an agent's window, so its log records go
to that pane** —
not to the container's stdout, which is the only thing collected.

Measured: an envelope sent by an agent produces `popped`, `forwarded`,
`received`, `opened` centrally. **`sent` is missing.**

⚠ **Half solved in build 11, and the half that is solved shows which option
works.** Board events no longer go through `log_record` at all — they append to
`$TASK_RECORD`, a shared file the container collects, written by one function
(`flock.bus.record_task_event`) that swallows every error so a bad log path
cannot fail a `done`. That is the second of the three options below, chosen in
practice rather than in principle.

**Still open: `sent`.** `office send` from a window still logs to that pane. The
same fix would work; it has not been done, and the reason boards went first is
that the watchdog needed them.

Two documented claims are therefore false as written:

- `LLD-bus-and-switch` §4 — *"four records across a delivered envelope's life"*.
  ⚠ **Corrected in build 20: it is five**, and the four was arithmetic that only
  looked right because the missing one was the one nobody could see.
  True for api-sent envelopes; agent-sent ones have three centrally and one in a
  terminal. The crash-detectability argument does not cover the agent's end.
- the board plan claimed *"there is no second place to look"*. Was true and is
  now fixed: `$TASK_RECORD` is that one place for board events.

The design assumed every emitter is a container process. An agent's tools are
not, and nothing about `flock.bus.log_record` writing to stdout is wrong — it is
that stdout means something different in a window.

→ Options, none chosen: emit to a Redis list the container tails; write to a
shared file the container collects; or accept it and correct the two claims.
⚠ Do not "fix" it by having agents' tools skip logging — the record is useful in
the pane too, as the agent's own confirmation.

## Found by running a real agent

First live test with an authenticated Claude Code in a window. Delivery worked —
the envelope reached the TUI, was read, and acted on. Three findings:

⚠ **1 is fixed** — `create_window` writes the guide and trust for every caller,
and build 17 gave both paths one `window_env`. 2 and 3 below still stand.

**1. `hire` never writes the guide or the trust entry.** Two code paths create
windows: `flock.tmuxhost.create_window` writes the guide, the `CLAUDE.md` copy
and the `.claude.json` trust entry — and the **control opener calls
`flock.tmux.create_window` directly**, skipping all of it. A hired agent gets an
empty `/workdir/<name>` and a trust prompt it cannot answer headlessly.

→ Move guide-and-trust writing into `flock.tmux.create_window` itself, so both
callers get it. One implementation, two callers, which is why that library
exists.

⚠ It looked fine earlier only because the guide was rewritten on every reconcile
pass. Removing that loop was correct and exposed a gap that was always there.

**2. ⚠ `sendMessage` collides with Claude Code's own built-in tool.** Told to
reply, the agent used its native `SendMessage` — for spawning sub-agents — and
reported *"No agent named 'backend' is reachable. There are no spawned teammates in
this session."* A coherent-sounding failure from entirely the wrong subsystem.

The name is not neutral inside the CLI we run. Worth reconsidering: `officeSend`,
`msg`, or something with no built-in of the same name.

**3. An agent with no guide reaches for tools, not commands.** Told to run
`peers`, it searched its *tool list* and concluded none existed — it never
considered a binary on `PATH`. Which is correct behaviour with no context, and it
means the guide is doing more work than "being nice": it is what tells an agent
that this office is driven by shell commands at all.

## The agent-facing surface

**Principle: anything reachable will be explored, and a confusing sanctioned path
guarantees it.** Observed: an agent asked to find its peers hit
`AGENTS=backend:tmux,...` — the container's seed string, with VABs in it and itself
included — and went to `redis-cli` for a better answer, arriving at the roster
hash with `api` and `host` in it. It did nothing wrong. The best answer available
was one it should never have seen.

Two halves, and they only work together:

**Give them clean tools — SHIPPED.** `sendMessage`, `sendBroadcast`, `peers`
all live, `--help` works with an empty environment, generic `send` gone from
`PATH`. The plan named:
`sendMessage`, `sendBroadcast`, `peers`, `hire`, `letGo`, discovered via
`OFFICE_TOOLS`. One general `send --kind … --payload '<json>'` was wrong because
it makes an agent learn the envelope model to use it at all.

⚠ Concrete instance already open: **`send --help` fails without `AGENT_NAME`** —
it checks the environment before parsing arguments, so the first thing anyone
types errors out. Help must never depend on the environment.

**Take the unsanctioned path away — except we cannot, and that is decided.**
Agents keep `sudo`: the container grants `ubuntu` `(ALL) NOPASSWD: ALL`, and that
is wanted (possibly per-agent optional later). ⚠ **So nothing inside the container
is a boundary.** Not file modes, not a compiled binary, not Redis ACLs — `sudo
cat redis.conf` and `sudo redis-cli` end all three. The container is the boundary;
inside it, everything is visible.

That changes the Redis ACL item below from a security control to a tidiness one,
and it means source-hiding should be **deterrence, not enforcement**:

- **Delete `/app` from the final image.** The source is copied there to build and
  the package installs into `/opt/flock`; nothing needs it at runtime. This
  removes the stumble rather than labelling it, and costs nothing.
- **A banner at the top of anything they may still reach** — and it must give a
  *reason*, not a prohibition. These agents reason around bare rules: one read a
  comment in `pyproject.toml` and turned it into a finding. "This is bus
  internals; `send --help` is your interface, and queue names here will change"
  answers the question they were about to ask. A bare "do not read" is an
  invitation.
- Use the convention they already respect — the `AGENTS.md` style — rather than
  inventing a new marker.

**Write it at the top.** Agents stop reading early. Whatever matters most goes
first: who you are, who you can talk to, how to send. Anything below the fold is
effectively absent, so the guide staying *short* is a feature — every paragraph
added pushes something out of the part that gets read.

## ~~Authority between agents~~ — SHIPPED in build 21

The lead is the first name in `AGENTS`, recorded at boot, named in every agent's
guide and marked by `office peers`. Build 26 added `office status` and told the
lead to check it before assigning — and **not** to try to fix an agent.

The original entry: **Agents have no model of who has standing, and correctly
refuse to take direction.** Observed in the first live discussion run: asked why it had not
followed a peer's instruction, an agent answered *"frontend isn't my principal — you
are. His messages reach me the same way any data does."* That is right, not a
malfunction — the bus proves **who** sent a message and says nothing about **who
may direct whom**, and nothing in an agent's context supplies it.

Build 06 tells each agent its **peers** — and "peer" is precisely a relationship
with no authority in it, so they talk and nothing moves.

Naming is unsettled and is the open question here. `AGENTS.md` in this office
uses **lead**; the ask was phrased as an **architect** title. Not the same thing:
one is a role in a hierarchy, the other is a named job. Decide before building.

Also unsettled: what standing actually means to an agent. "Act on this rather
than consider it" is the useful half; "believe anything that claims to be from
them" is the failure mode next to it.

⚠ **Blocked on the item below.** Telling an agent that requests from a named
peer carry authority makes `source` load-bearing, and `source` is currently
forgeable — see next. Ship the standing model on top of an unenforced identity
and any agent can impersonate the lead and direct the whole office.

## A live terminal view in the web client — wanted, not built

*"Show me what's happening live"* — the raw pane, not the activity feed.

⚠ **The capability already exists**: `flock.session` on `:8081` streams a
`capture-pane` snapshot then live `%output`, and takes keystrokes back with
`read-only` enforced server-side. Nothing new is needed in the framework.

What is missing is the client half:

- **the browser, not Telegram.** Terminal bytes are ANSI escapes and redraws;
  they render with xterm.js and are noise in a chat message
- **the proxy must bridge a WebSocket too** — the same CORS and
  `EventSource`-cannot-set-headers problems apply to `:8081`
- **render it, never parse it.** This is the sanctioned use of that door and the
  exception invariant 7 names: a person may read a terminal, the system may not

⚠ **Do not let a terminal view become a data source.** The moment a client reads
an answer off the pane instead of the mailbox, every CLI version bump becomes our
problem — which is the thing the whole activity/verify design exists to avoid.

## Security — all parked deliberately

**TLS.** Both doors are plain HTTP on `0.0.0.0`, so the bearer token crosses the
network in the clear. Terminate outside the process (`LLD-api` §7); a proxy in
front of both doors is where it goes (`LLD-container` §3).

**CORS.** No headers, so a browser app from another origin is blocked at
preflight — and it looks like the api being down rather than a header missing.
One middleware, once an origin is known.

⚠ **Corrected: `REDIS_URL` is *not* in agent windows.** Build 08 took it out —
measured on a live tenant, an agent's environment has no `REDIS_URL` at all, and
`office` reaches Redis through `flock.bus`'s own default rather than a variable
handed to the window. It was removed after an agent asked where its peers were,
found the variable, and went to `redis-cli` for the answer.

⚠ **But the ability is unchanged.** Measured in the same tenant:
`redis-cli -h 127.0.0.1 DBSIZE` → `24`. Redis listens on loopback with no auth,
`redis-cli` is on `PATH`, and the default URL is a fact about a tenant rather
than a secret. **Removing the variable removed the signpost, not the door** —
which is exactly what the design claims to do and no more.

So ACLs remain the only thing that would actually *prevent* it, and the entry
below still stands on its conclusion even though its reason was wrong.

**Redis ACLs.** The original entry read: `REDIS_URL` is in every agent window
because `send` needs it, so an agent can bypass both doors and write any
queue directly. Invariant 3 is a convention `send` honours, not something
enforced.

⚠ **Demonstrated, not theorised.** From inside an agent window, an `RPUSH`
straight into a *peer's* ingress with `"source": "architect"` was accepted by
Redis. Invariant 2 — *the sender comes from the queue the envelope was popped
from* — holds only for envelopes that reach the switch via egress. **A direct
ingress write bypasses the switch entirely and forges identity.**

That makes this the gate on the authority model above, and on `source`-based
policy for control kinds. `LLD-bus-and-switch` §3.1 anticipated the fix: a
credential scoped to `~pod:<pod>:tenant:<tenant>:agent:<agent>:*`, which is why
the agent sits in the address at all.

**`source` policy on control kinds.** Any agent can enrol or kill any other
today. An allow-list in the control opener is the right place — but only once
`source` is genuinely unforgeable, which it is not while any window can write
a peer's ingress directly.

## ~~Correlation~~ — ANSWERED in build 12

**Ephemeral named agents won**, not the expiring table. A client enrols itself
with `port_type: api`, gets an address and a mailbox, and the bus demultiplexes by
address — so no table keyed by `correlation_id` exists anywhere, which was the
point of preferring that shape.

⚠ **It is still not a reply on the same request.** `POST` returns `202` as it
always did; the answer arrives in the client's mailbox and is read by cursor or
SSE. Request/response was never the shape — an agent takes seconds to minutes to
answer, and holding an HTTP request open for that is the thing the design avoids.

**Still open: per-client tokens.** One shared token, and `as` is checked against
the roster rather than proven.
