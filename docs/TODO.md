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

⚠ **This file says what is open. [`SPRINTS.md`](SPRINTS.md) says in what order,
batched with what else, and against which test run.** Rows here are unordered on
purpose — pick from the sprint plan, not from the top of this table.

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
| **seeded credentials do not survive `--force-recreate`** ⚠ *half of this row was already false* | They live in the container filesystem by design — never baked, never a volume — so recreating deletes them, and `seed-home.sh out` before a rebuild is still the only way back. ⚠ **But `seed-home check` does NOT lie any more.** This row said it reported "logged in" by testing the *host's* staging copy; it runs `docker exec` and tests paths **inside** the container, per profile, including `.claude-<p>/.credentials.json` and `.codex-<p>/auth.json`. Corrected 2026-08-23 by reading it rather than trusting the row. ⚠ **`out` covers profiled directories too** — `CRED_PATHS` for the three unprofiled plus a glob over `.claude-*` and `.codex-*`. ⚠ **agy has NO per-profile support anywhere**: `window_env` sets `CLAUDE_CONFIG_DIR` and `CODEX_HOME` for a profile and nothing for agy, `ensure_agy_project_trusted` takes no profile, and `check` sets `agy_path=""` for any non-default account. **One agy account per tenant**, however many accounts are configured, and nothing says so at setup. ⚠ **What remains**: the round trip itself — `out`, rebuild, `in` — is the manual step, and the OAuth token removes it for claude only |
| **`office swap <agent> --cli <x>`** ⚠ *operator's idea, and mostly already built* | The CLI is a Redis value (`agent:<name>:launch`) and `tmuxhost` rebuilds a missing window from it, so replacing the process while keeping the name, board, queues and workdir needs no new machinery. ⚠ **Not stop-then-start:** `StopAgent` destroys an api client's unread mailbox (audit F6). Open questions: drain or discard the ingress, what presence reads during the gap, and what happens to a ticket already in `doing`. Costs the agent's memory, which is acceptable |
| ~~**a local provider only works for claude**~~ **— CLOSED in `afd2e25`, and the row outlived it by a day** | ⚠ **Verified 2026-08-23 by grepping the tree**: there is no `ANTHROPIC_*` construction left in `src/`, only two comments recording that there used to be. h-flock delegates to base, so a codex or agy agent with a provider now **refuses to start** instead of silently running against the vendor. ⚠ **Nobody marked this row when the work landed** — the same failure the index warns about at the bottom of this section, caught here only because a sprint plan re-checked every citation. The original: | ⚠ **Base gained `AGENT_PROVIDER_URL` / `_MODEL` / `_SMALL_MODEL` / `_TOKEN` on 2026-08-23**, and — the part that matters — **`startAgent codex` and `startAgent agy` with those set exit 3 rather than starting**. That is exactly the loud refusal this row asks for. ⚠ **h-flock does not use it**: `tmux/ops.py` still builds `ANTHROPIC_*` itself, so a codex agent with a provider still runs against the vendor while `setup.sh` prints `(local)` beside its name. **Delegating to base would close this row and delete code rather than add any.** The original: | `tmux/ops.py:258-291` sets `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN` and the three tier model variables. codex reads `OPENAI_BASE_URL` / its `config.toml`; agy supports no custom provider at all. **Assign a provider to a codex agent today and it runs against the vendor while `setup.sh` prints `(local)` beside its name** — cost and privacy both differ from what the operator was told. ⚠ **The cheap half is the refusal**: say it plainly at the prompt and log it when a non-claude agent carries an `provider`. The real fix is `OPENAI_BASE_URL` support for codex. Measured 2026-08-12 while planning to use a second vLLM |
| ~~**`[message from x]` is an amateur sender field**~~ **— WON'T FIX, decided 2026-08-23** | ⚠ **The data half was already done and the presentation half is correct as it stands.** `source` is 63 fixed bytes in the v4 header (`src/flock/bus/envelope.py`), parsed by offset, so the sender **is** a field everywhere it needs to be. The string survives in exactly one place — `src/flock/port/openers.py:95`, the tmux opener — and the sibling opener at `src/flock/port/openers.py:126` pastes bare text, which is the proof it is presentation and not a format. ⚠ **The consumer is an agent reading a terminal**, and `[message from architect]` is close to the ideal rendering for that reader: short, unambiguous, survives paste. ⚠ **It is also a published contract in two places** — `src/flock/api/app.py:351` documents it and `src/flock/tmux/ops.py:98` teaches it to every agent in the guide — so changing it changes what we tell agents a message looks like. ⚠ **The one real complaint was that delivery tests count by grepping for it. That is a liability only if the string changes**, and this decision is that it does not. Operator's call, and the right one: it works, and every argument for changing it was aesthetic. The original: | Every delivery arrives as the literal text `[message from alice] …` pasted into the pane, so the sender is a **string inside the message body** rather than a field. It cannot be styled, filtered, parsed or trusted, it collides with message content that happens to contain the phrase, and every test in this repo counts deliveries by grepping for it — including the 100- and 4-agent benchmarks. ⚠ **Needs a proper sender presentation**, and a test that asserts the sender is carried as *data* rather than as decoration in the text |
| ~~**a failed send leaves no trace anywhere**~~ **— BOTH HALVES CLOSED, (b) by build 87** | ⚠ **(a)** `send_refused` and, since build 92, `send_unknown` are records on the bus rather than prose in a pane. ⚠ **(b)** was *"needs an interface that is never shell-parsed"* — `office send --stdin` and `--file` exist, mixing is refused, empty stdin is refused, and the acknowledgement carries the byte count so a truncated body is visible to the sender. The original: | ⚠ **(a) is closed.** `bus/doors.py:74` emits `send_refused` with the reason for every resolution or policy failure, and `bus/doors.py:86` emits `send_failed` when the egress write itself throws. Both are records on the bus, not prose in a pane. ⚠ **(b) is untouched** — an `office send` whose quoting breaks is still never invoked, so there is nothing to record; that needs the never-shell-parsed interface, and no build has taken it. The original, for the second half: Two depths, one symptom. **(a) `office send` runs and fails:** measured — `office: error: unknown destination agent 'operator'` was printed into a pane and recorded **nowhere** — not the bus, not the container log, not an alert. The command knew it had failed and told only the terminal. **(b) the shell eats the line before `office` runs:** `office send -a x "body"` puts prose on a command line, so broken quoting means our tool is never invoked at all — measured as `/bin/bash: line 14: VERIFIED-MODE: command not found` from an agent's own message. ⚠ **(a) is a missing log record; (b) needs an interface that is never shell-parsed** (`--stdin`, a file, a heredoc). ⚠ **Neither is an escalation** — the agent already has full Bash — and the model's quoting discipline is the proximate cause of (b), but the silence is ours |
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
| **correct `API.md:53` — the fabric mints `correlation_id`, it does not propagate one** ⚠ *DECIDED 2026-08-23: keep minting, fix the document* | `src/flock/api/app.py:651` runs `correlation_id = uuid.uuid4().hex` **unconditionally**, discarding anything the caller sent. `docs/API.md:53` says *"Propagated from request or minted automatically"*, and `LLD-api` designs it as the thread join key for external clients. ⚠ **So no external app — console, bot, webhook — can continue a thread across the REST door**, and the public reference promises that it can. ⚠ **This is not a one-line fix, it is a decision.** Propagating a caller-supplied id means a client can **join a thread it was not part of**, because `correlation_id` is the key the whole custody log joins on. The honest options are: accept it and validate the shape (32 lowercase hex) since the door already trusts a bearer token for `as`; accept it only when the caller also owns the referenced stream; or keep minting and **correct the document**. ⚠ **Related, same property on the other surface**: the agent-facing row above — `office send` neither shows a `correlation_id` nor accepts one. Both doors are blind to the same field. ⚠ **DECISION, on `api`'s recommendation and its reasoning, not mine**: keep minting unconditionally and **correct the document**. ⚠ **The argument that settled it — half-threading is worse than none, because it looks like it works.** A bot would pass a `correlation_id`, see it accepted, and reasonably conclude threading works; the agent's reply through `office send` mints a fresh one regardless, so the thread breaks silently at the second turn. That is the exact failure class this repository spent 2026-08-23 removing. ⚠ **The other two options were rejected on cost, not on principle**: verifying stream ownership needs an inbox lookup on the ingest path before anyone has designed how agents reference threads, and blind shape acceptance lets an unauthenticated caller forge a join key with no per-client identity at the door. ⚠ **The CAPABILITY is not cancelled, it is deferred to a threading sprint that covers BOTH doors** — `office send --reply-to` and API propagation designed together, with tenancy boundaries. **Work remaining here is one sentence in `API.md`.** |
| ~~**a swallowed `_kick` failure is reported as an ACKNOWLEDGED fact**~~ **— SHIPPED in build 95** | `_kick` raises a typed `ProvableActualFailure` instead of absorbing a `Popen` `OSError`, so `resume_agent` can no longer append an acknowledgement for a process that never spawned. ⚠ **A fourth outcome exists**: `{kind}_partially_failed`, for a named subset acknowledged and a later named action **provably rejected**. It is the **first record to earn the reserved word back** since build 92 took it from five others — a `Popen` rejection reaps the child, so the non-occurrence is known rather than unknown. ⚠ **`tmux` argued that fourth shape rather than being given it**, eliminating the other three by name; the architect declined to specify it, having been wrong on this contract four times. ⚠ **Renamed from `_partial` on `bus`'s refusal**: `partial` and `incomplete` are ordinary-language near-synonyms denoting known-broken-and-actionable versus unknown-and-not, which licensed the very inference ruling 11 prevents — one level up, at the event name. The original: | `src/flock/control/runner.py:16-20` catches `OSError` from `subprocess.Popen`, logs `event: error`, and **returns normally**. So at `src/flock/control/openers.py:331-333` `resume_agent` sees the kick succeed, appends `kick N` to `actual_acknowledged`, and can emit `resume_agent_accepted` **when no port process was ever spawned.** ⚠⚠ **That is the exact inversion build 91 exists to prevent** — build 91 spent five refusals establishing that acknowledged is a FACT, and a swallowed exception manufactures one. It is worse than reporting `failed` where the outcome is unknown, because a false negative invites a retry while a false positive invites nothing at all. ⚠ **One half of the report I would argue with, and it does not weaken it**: `tmux` reads the exception as UNKNOWN. For `Popen` specifically an `OSError` means fork/exec failed with the child already reaped, so **no process exists and `failed` is provable** — this is the rare case rule 5 reserves. **The defect is the swallow, not the word.** ⚠ **Related but not the same as** the pause/resume row above, which says those paths are untested live; this names a defect that would survive testing them, because the record would read `accepted` either way |
| ~~**build 92's unicast conservation has no behavioural control**~~ **— SHIPPED in build 96** | `container/scenarios/reconcile-unicast.py` is executable and `conservation.sh:161` invokes it with the unchanged five inputs; removing the indeterminate branch now falls through to `LOSS_UNEXPLAINED` and fails. ⚠ **The extraction risk was answered rather than ignored** — `api` verified the extracted reconciler matches the original heredoc across **seven** scenarios where `bus` had reported one, because two paths agreeing on a single input prove nothing about the branch under test. The original: | `container/scenarios/conservation.sh:297` carries the indeterminate branch and `:316` prints `INDETERMINATE_FORWARD`, but `tests/test_conservation_contract.py` executes only `analyse-run.py` and `reconcile-broadcast.py`. **No committed test drives the unicast heredoc and demonstrates `rc5`, `lost=0`, `indeterminate=1`.** ⚠ **The code reads correctly and the claim is uncontrolled**, which is exactly the defect class that got build 92's first submission refused — left on the other path. ⚠ **`bus` found this in its own build after it merged**, which is the argument for alignment rounds: a lane will audit its own work when asked a question it cannot answer with the work itself. **Fix as `bus` proposes**: extract the unicast reconciler, drive a synthetic `forward_unknown` through it, and show that removing the indeterminate branch produces `LOSS`/`rc1` |
| **h-office `sendMessage` still loses a message body to shell parsing — measured on the architect** ⚠⚠ *2026-08-24, and it cost a blocked lane a round trip* | Build 87 removed `argparse.REMAINDER` from `office send` because an agent sent the literal word `--stdin` instead of its report. ⚠ **The office's OWN bus still has the defect.** The architect sent a lane its lab disposition containing a `$(...)` construct; the shell substituted it, `sendMessage` reported **`✓ delivered`**, and **the lane received nothing** — it had to ask for the message to be resent while its build sat blocked. ⚠⚠ **The acknowledgement was the worst part**: a success line was printed for a message that did not arrive. That is the same class as `office send` returning a bare stream id — an ack that confirms the call, not the content — which build 87 fixed by reporting **bytes accepted**. ⚠ **Not an h-flock defect and not h-flock's to fix**; recorded because it is the strongest available evidence for why `--stdin` and `--file` were worth a build, and because **the architect demonstrated it while describing a leak.** ⚠ **Working rule until h-office changes**: no `$( )`, backticks or unquoted metacharacters in a message body — and if a lane goes quiet after a long message, **suspect the transport before the lane.** |
| ~~**the console proxy takes its token and secret as ARGV**~~ **— SHIPPED in build 101, and it cost nothing** | ⚠ **`clients/web/server.py` already defaulted both from `API_TOKEN` and `HFLOCK_SECRET`.** The capability existed and `accept.sh` passed flags anyway — so the fix was to export and drop them, with **`clients/` untouched and no freeze exception needed.** The launch line now carries only the listen address, port and two URLs, confirmed by the verifier sweeping it for anything else sensitive. ⚠ **Worth remembering how it was found**: by reading a `ps` output while deciding which PIDs to kill, which is not a systematic method — nobody went looking. The original: | `clients/web/server.py` is launched as `python3 server.py --listen 0.0.0.0 --port N --api … --token <TOKEN> --secret <SECRET>`. ⚠ **Command lines are world-readable.** Any user on that host — and any process that shells out — can read both credentials from `ps` or `/proc/<pid>/cmdline` for as long as the process lives. ⚠⚠ **And the leaked orphans made that lifetime unbounded**: two consoles have been advertising a live API token and session secret on the lab for **four hours and one hour** respectively, long after their tenants were destroyed. **The leak turned a scoped exposure into a permanent one.** ⚠ **This is the argv row of the transport-hygiene ranking we already wrote for `setup.sh`** — a silent prompt beats history, a file beats argv — and the console is the one place we did the argv version anyway. **The fix is an environment variable or a file descriptor, not a flag.** ⚠ **`clients/` is closed to development**, so this is recorded rather than scheduled; but a credential visible in `ps` is a different weight from a broken demo, and it is worth asking whether that freeze should hold for this one |
| ~~**`accept.sh --keep` leaks its console proxy forever**~~ **— SHIPPED in build 101** | `--keep` now transfers ownership **out loud**: the `kept:` line names the container **and** the console PID with the command to stop it. ⚠ **Killing it was rejected as the fix** — `--keep` exists so an operator can work on a live tenant and the console is part of what they kept; the defect was that ownership transferred silently. The original: | `container/accept.sh:83` returns from `cleanup()` when `KEEP=1` **before reaching line 87's `kill "$CONSOLE_PID"`**. The console proxy is a **host process**, so `docker compose down -v` never touches it: an operator tears the tenant down correctly and the console survives forever. ⚠⚠ **The two "unexplained `python3` processes" holding ports 8099 and 8199 were `acceptance`'s own leaks from builds 90 and 94.** The lab drift reported as possible host noise was **our harness**. ⚠ **The convention rule paid for itself in one run**: build 94 worked around 8099 and moved on; §3.0 then required naming what holds a default before working around it, and the next run traced the occupant to a line anyone could have read. ⚠ **The fix is not simply to kill it** — `--keep` exists so an operator can work on a live tenant, and the console is part of that. **The `kept:` line must name EVERYTHING the operator now owns**, console PID included, because `--keep` transfers ownership and currently transfers it silently. ⚠ **Two orphans remain live on the lab** (PIDs 2790629 and 2838728); `acceptance` reported and did not remediate them, correctly. The original observation: | ⚠ **Four acceptance runs out of four (86, 89, 90, 94) began with the VM already swapping** — 1.2–1.9 GiB free of 7.8, and 1.1–1.9 GiB of swap already in use — **before a single container was created**. ⚠ **Build 94 found port 8099, the harness's own default console port, held by an unrelated `python3` process nobody can account for.** It worked around it with `--console-port 8199` and moved on, which is what anyone would do, and **the process is still there.** ⚠ **This is the shape of the four stranded networks that builds 84 and 85 found** — silent accumulation on a shared host that nobody owns between runs — except in ports and memory, and with **no `BUILD-CONVENTION` §3.0 rule that catches it.** It is visible at all only because `BUILD-83` happens to make the seat check ports and free memory before every run. ⚠ **Reported as a measured pattern, not a diagnosis** — it may be ordinary noise from other lanes' containers. **Someone has to own the lab between runs, or write the rule that notices** |
| ~~**`docs/LLD-port-tmux.md:150` still describes the pre-build-92 vocabulary**~~ **— SHIPPED in build 95** | Corrected in `tmux`'s own lane, alongside the swallowed-kick fix. The original: | It says every exception logs `board_write_failed`; the exception path now logs `board_write_unknown`, and `board_write_failed` survives only for a **returned** invalid depth. ⚠ **`bus` found it while editing a different file and reported rather than fixed it**, which is correct — contradictions inside the file you are editing are in scope, contradictions in someone else's are a row. ⚠ **tmux's lane owns it.** Small, and it is a documented falsehood until done |
| **`send` and `broadcast` now take their body differently, and nothing says so** ⚠ *found in the README the moment build 87 shipped* | Build 87 removed `argparse.REMAINDER` from `send` — the body is now **one quoted argument**, or `--stdin`, or `--file`. ⚠ **`broadcast` kept REMAINDER deliberately**, so `office broadcast standup in five` still works while `office send -a bob standup in five` is rejected. **Two adjacent commands, two conventions, and the agent guide teaches only one of them.** ⚠ **Measured cost already**: `README.md` shipped an `office send` example that the merge had just broken, and `docs/API.md` still shows the old form. ⚠ **Decide, do not drift**: either `broadcast` loses REMAINDER too — same argument, same defect class, and it is the one command that fans out to everyone — or the difference is stated wherever either is taught. The mistyped-flag-becomes-body bug that started this **still exists on `broadcast`** |
| ~~**five records say `failed` where the outcome is UNKNOWN**~~ **— SHIPPED in build 92** | ⚠ **The events were RENAMED, not just reworded** — `send_unknown`, `board_write_unknown`, `kick_unknown`, `forward_unknown` — because an event *named* `*_failed` uses the reserved word however careful its reason text is. `board_write_failed` survives in exactly one place: a **returned** invalid depth, where the rejection is provable. ⚠ **Conservation carries an unresolved `forward_unknown` as its own bucket**, prints `INDETERMINATE_FORWARD` and exits 5 — never folded into forwarded or loss, never retried. That was the lane's call to argue and it is the right one: the check can now say *"n indeterminate"* instead of reporting a phantom loss. ⚠ **A custody file spanning the rename is REFUSED (rc4)** rather than classified two ways, which is the honest answer to a vocabulary change mid-history. ⚠ **The refusal that found the real defect**: the first submission fixed unicast, documented both, and left the BROADCAST reconciliation still folding an ambiguous forward into known loss — the exact phantom the build existed to prevent. It escaped because the conservation test read source text and asserted strings; it never executed reconciliation. The original: | Build 91 spent four rounds proving that **an exception is the absence of an answer, never evidence the thing did not happen** — a Redis write can commit and lose its reply. ⚠ **The same pattern is in five places outside the control plane**, each emitting a `*_failed` record from an exception handler over a write that may have succeeded: `src/flock/bus/doors.py:86` (`send_failed`), `src/flock/port/openers.py:191` (`board_write_failed`), `src/flock/switch/service.py:84` (`kick_failed`), and `src/flock/switch/service.py:164` and `src/flock/switch/service.py:183` (`forward_failed`, broadcast and unicast). ⚠⚠ **The two `forward_failed` sites are the dangerous ones.** An ingress write that committed and lost its reply puts the envelope **on the recipient's queue** while the custody log records it as not forwarded — so the conservation invariant reads a loss that did not happen, and anything that responds to that record by re-sending produces a **duplicate delivery**. `HLD` makes at-most-once the property the whole design exists to hold, and duplicates an absolute defect. ⚠ **`send_failed` invites the same by a different route**: an agent reads *"egress write failed"* in its pane and does the natural thing, which is run the command again. ⚠ **The fix is wording plus one decision, not retries** — say `outcome UNKNOWN after <exc>` per `BUILD-91` ruling 11, and decide what the conservation check does with an envelope whose forward is indeterminate. **Natural follow-on to build 91 and it is mechanical**; the decision is not |
| ~~**join `window_created` to the control record**~~ **— SHIPPED in build 103** | `tmuxhost` takes a one-shot `window.cause` and emits `window_created` carrying the `correlation_id` of the hire that caused it, so the two records join. ⚠ **Roster `HSET` before cause `SET` in one Lua call** — Redis Lua cannot roll back, so the ORDER decides which partial is observable, and cause-without-roster is now impossible. A window rebuilt with no hire behind it emits no `correlation_id`, which is a fact rather than a gap. The original: | Build 91's opener records what control **accepted**; actual state is applied asynchronously by `tmuxhost.reconcile_once`. ⚠ **This row assumed `tmuxhost` needed a new confirmation record. It does not** — `src/flock/tmuxhost/host.py:116` and `src/flock/tmuxhost/host.py:150` **already emit `window_created`** with a `destination`. ⚠ **The only thing missing is the `correlation_id`**, so the two records cannot be joined and nothing can say *which* hire produced *which* window. ⚠ **Measured on a live tenant, not estimated: 4.091 s** between `start_agent_accepted` and `window_created` for the same agent (`BUILD-94-results`). **Thread the correlation_id through and the confirmation exists.** ⚠ **Do NOT make control wait** — that turns an asynchronous architecture into a gate, and window presence does not prove correct configuration |
| **the failure shapes are now REACHABLE — one is reached, the rest are not** ⚠ *build 100 closed the hard half; what remains is coverage, not capability* | ⚠⚠ **A real `forward_unknown` exists on a live tenant.** Conservation met it and returned `sent=1 indeterminate=1 lost_attributed=0 lost_unexplained=0`, `INDETERMINATE_FORWARD`, `rc5`. **Build 92 taught conservation to carry an indeterminate forward instead of reporting a phantom loss, and nothing had ever given it one until now.** ⚠ **The shipped path pays nothing**: the machinery is entirely in `container/scenarios/` and `tests/`, and `src/` carries no injection check at all — a mechanism that does not exist unless deliberately assembled. Every injected record carries `writer: fault-injection` so it can never be mistaken for a genuine one. ⚠ **What remains**: `_incomplete`, `_failed` and `_partially_failed` on the four CONTROL kinds are still at zero live. **That is now a coverage question rather than an unreachable one** — the harness exists and the pattern is proven. ⚠ **Do not chase all of them.** Each costs a live tenant and a fault; take one when it answers a real question, and keep the acceptance seat's count honest in the meantime. The original: | ⚠ **Build 97 closed half of this by running them**: `pause_agent_accepted` and `resume_agent_accepted` both fired, each naming the agent with a `correlation_id`, and both were confirmed against reality rather than the log — the Redis paused marker present then gone, a message queued while paused that did **not** reach the pane and **did** arrive after resume. ⚠ **Measured, not estimated: 0.251 s** between `resume_agent_accepted` and the queued delivery completing — the same shape as build 94's `window_created` gap, and more evidence that `_accepted` is a separate step from the work it triggers. ⚠⚠ **What remains is the whole point**: `_incomplete`, `_failed` and `_partially_failed` are **still zero occurrences across all four kinds.** Six builds and eleven refusals argued those records into shape and **nothing has ever produced one outside a unit test.** ⚠ **They cannot be reached by running the system harder** — they need a Redis write to lose its reply or `Popen` to fail. **A fault-injection harness is the honest way to close this**, and `acceptance` was explicitly told not to stage one: a manufactured fault proves what the unit tests already prove and would put a fabricated record in a real custody log. The original: | A full acceptance run's custody log carries **11 `start_agent_accepted` and 15 `stop_agent_accepted`** — both kinds genuinely exercised, by more paths than expected. ⚠ **`pause_agent_*` and `resume_agent_*`: ZERO occurrences.** Nothing runs them — not `accept.sh`, not `plumbing-check.sh`, not `flow-check.py`. ⚠⚠ **And `*_incomplete` and `*_failed`: ZERO, for all four kinds.** Build 91 spent **five refusals** getting those two shapes right and **neither has ever been exercised outside a unit test.** ⚠ **This is a statement of what is unverified, not a suspicion that it is broken** — the shapes may well be correct. But the two outcomes that matter when something goes wrong are the two nothing has ever produced live | Build 91's opener records what control **accepted** — desired-state writes committed. ⚠ **It cannot say the hire worked**, because `tmuxhost.reconcile_once` applies actual state asynchronously: a fresh hire returns before any window exists, and a changed hire only kills the stale window so reconcile can rebuild it. **Wanted**: `<kind>_pending` at the opener, `<kind>_confirmed` from `tmuxhost` once the window is actually there. ⚠ **Do NOT make control wait for it** — `tmux` argued this and is right: waiting turns an asynchronous architecture into a gate, and window presence does not prove correct configuration. ⚠ **Found by `bus` refusing the architect's own ruling**, which had defined `_confirmed` as *"desired state committed and actual state followed"* — a thing no opener in this design can know |
| **control desired-state writes are not atomic — MEASURED, and the residue is worse than untidy** ⚠⚠ *build 102 spike, 2026-08-24: an agent that looks GONE and comes back BROKEN* | `stop_agent` writes twice — `hdel` on the roster, then `purge_agent` — and `start_agent` writes several times, with no transaction. A failure between them leaves the agent **half-removed**, and Redis cannot roll back committed commands. ⚠ **Build 91 makes the RECORD truthful** (`<kind>_incomplete`, naming the committed subset) **without making the failure impossible**, which was a deliberate call: the record is the build's job, atomicity is a design change. **The option is a Lua script**, as `watchdog/activity.py` already uses for usage emission — `purge_agent` plus the roster `hdel` as one server-side operation. ⚠ ⚠ **The weighing is done and the evidence is in.** Build 102 injected a fault between the roster `hdel` and the resource purge on a live tenant. **What survives**: `launch`, `profile`, `provider`, `paused`, `blocked`, `pending.verify`, `tags`, `delivery.markers` — and **the `delivering` lock is left held**. ⚠ **The agent does not look broken. It disappears** — `office status` and `office peers` show nothing at all, because the roster row is the thing that did get removed. ⚠⚠ **And a later `StartAgent` for the same name SUCCEEDS**, republishing the roster while clearing none of it. So the re-hired agent silently inherits a `paused` or `blocked` marker and **a stuck delivery lock, meaning mail in its ingress cannot be delivered.** ⚠ **Two candidate fixes and they are not the same shape**: make the purge atomic with a Lua script, as `watchdog/activity.py` already does — or make `start_agent` **defensive**, clearing the operational markers it does not set. ⚠ **The second is cheaper and covers more**: it also handles residue from a crash, a manual Redis edit, or an older version, none of which atomicity prevents. **Atomicity stops us creating the mess; a defensive start survives a mess from any source.** ⚠⚠ **AND A THIRD, DERIVED FROM BUILD 103, CHEAPER THAN BOTH: reorder the writes so the only observable partial is the HARMLESS one.** `tmux` solved this same class of problem by putting the roster `HSET` before the cause `SET` inside one Lua call — **Redis Lua cannot roll back, so the ORDER decides which partial can exist**, and roster-first makes the dangerous one impossible rather than cleaning it up afterwards. ⚠ **The same reading applies to `stop_agent` and costs nothing.** It removes the roster row **first** and purges resources after, so the dangerous partial is exactly the one that happens: agent vanished, residue intact, restart inherits it. **Purge the resources first and remove the roster LAST**, and a partial instead leaves an agent still in the roster with its state already cleared — **visibly present and harmless, instead of invisibly broken.** ⚠ **A reordering, not a transaction**: no Lua, no new failure modes, and it converts an invisible corruption into a visible one. **Decide between the three** |
| **a revoked OAuth token is invisible to the watchdog** ⚠ *the cost of fixing the false `absent` alert, and it is mine not a lane's* | Build 91 stops `watchdog/service.py` alerting `absent` forever for a token-authenticated agent — correct, because that agent has no credentials file **by design**. ⚠ **But it skips the check entirely rather than checking something else**, so an agent whose token was **revoked or expired** is dead and the watchdog is silent. That is precisely the case the check exists for. ⚠ **Not fixable locally**: a token cannot be validated without an API call, and presence in the window environment is the only signal available offline. So the honest options are a periodic authenticated probe, or leaving it and saying so. **It is said** — in `BUILD-91-results` and at the `continue` itself. ⚠ **Recorded because neither the author nor either verifier raised it**; three people read that diff and the silence was invisible to all of them, which is the argument for writing limits down rather than trusting review to surface them |
| **⚠⚠ acceptance reconciles NOTHING — 32 scenarios exist and it invokes zero of them** ⚠ *2026-08-24: the harness records six stages per envelope and the gate never opens the file* | `container/accept.sh` executes exactly four things: `setup.sh`, `plumbing-check.sh`, the console proxy, and `flow-check.py`. ⚠ **`container/scenarios/` holds 32 scripts, six of them analysis and reconciliation** — `conservation.sh`, `reconcile-unicast.py`, `reconcile-broadcast.py`, `analyse-run.py`, `analyse-v4-aof.py`, `analyse-verification.py`. **None is invoked by acceptance.** ⚠⚠ **So every acceptance run in this project's history has passed without once checking what was sent against what was delivered.** `EXIT 0` has always meant *the plumbing works*; it has never meant *the envelopes conserved*, and the architect has reported the first as the second all week. ⚠ **Build 113's four losses would have been invisible** to a normal run — every gate green. **The `2003 delivered against 2000 expected` in `BUILD-47` sat unexamined for weeks** for the same reason. ⚠ **`bus` built the reconciler in builds 92 and 96, `bus` was refused twice over it, `api` verified the extraction across seven scenarios — and it has never run outside its own test.** ⚠ **Cheapest large win available**: the tooling exists and is verified. What it needs is one invocation and **a decision about what a non-zero reconcile does to the exit code** — which is not mechanical, since `INDETERMINATE_FORWARD` exits 5 and acceptance currently means `1+` failed, `100` skipped, `0` clean |
| **acceptance never exercises `office usage` or `office status`** ⚠ *found while about to run a pointless acceptance* | Neither `container/accept.sh` nor `container/plumbing-check.sh` invokes either command **anywhere**. ⚠ **Measured 2026-08-23**: a full green acceptance run covered **none** of build 88, which changed both renderers — so the harness would have passed, told us nothing, and read as if it had. The two commands an operator is most likely to read are covered by unit tests only. The live check had to be driven by hand (`BUILD-90-results` part 2). ⚠ **Same defect class as the console flows skipping for weeks**: a harness that does not reach something reports success rather than silence |
| **codex `rate_limits` has never been seen working live** ⚠ *half of build 82's successor is unproven* | `office usage` surfaces `used_percent`, `resets_at` and `plan_type` from codex `token_count` records. It passes against `tests/fixtures/codex-session-captured.jsonl` and **has never run against a live codex agent** — the 2026-08-23 acceptance tenant had none, so `office usage --json` correctly carried no `rate_limits` on any row. ⚠ **Not a defect, an untested claim.** Needs one tenant with a codex agent that does real work |
| **`office status` says `unknown` for an agy agent while the column beside it says why** ⚠ *found by the acceptance seat, 2026-08-23* | After build 88 the **activity** column correctly reads `not measurable (agy)`. The **status** column still reads `unknown`, where claude agents read `idle`. ⚠ **That is one word doing two jobs one column apart** — *"we cannot determine this"* and *"we know, permanently, that this cannot be measured"* — which is exactly the confusion build 88 removed from the activity column and left in place next to it. ⚠ **Open question, not a verdict**: whether presence is genuinely underivable for agy, given a tmux pane exists either way, has not been established. The seat flagged it and declined to decide it |
| **an alert you can clear** ⚠ *asked for by the operator* | Alerts are an append-only stream with no acknowledgement. Clearing must be keyed by **cursor** — one instance — so it can never become "mute this kind". Spec: `BUILD-38-durable` §1 |
| **credential alerts never clear** | Measured: `status=absent` raised at `01:00:42Z`, login completed at `01:07Z`, nothing ever retracted it, so the console correctly rendered a fact that had been false for an hour. ⚠ **It was only ever tested firing.** `BUILD-38-durable` §2 |
| **the permission mode lives only in argv** ⚠ *probably closed, and the trigger was never reproduced* | ⚠ **The base image now ships `skipDangerousModePermissionPrompt: true` in `~/.claude/settings.json`**, and a file survives the CLI self-re-exec that argv does not — which is the exact mechanism this row describes. h-flock inherits it since 2026-08-23 and no longer ships its own copy. ⚠ **Not marked closed**, because the original trigger was never reproduced (*"a forced resize does not reproduce it"*), so there is nothing to test the fix against. If an agent is seen asking for permission again, this row is why. The original: | A hired agent starts as `claude --dangerously-skip-permissions …` (verified at +4s/+8s/+12s) and was later seen as bare `claude` carrying `CLAUDE_CODE_RELAUNCH_*`: the CLI re-executed itself and the flag went with it, leaving the agent asking for permission. ⚠ **The trigger is unknown** — a forced resize does not reproduce it. `BUILD-38-durable` §3 |
| **console conversation needs `--audit-log`** | Outbound messages are rebuilt from the audit log, so without that flag every refresh looks like data loss. Agent replies survive; yours do not. `BUILD-38-durable` §4, and a failing flow in `clients/web/flow-check.py` |
| ~~**no acceptance seat**~~ **— FILLED 2026-08-23** | ⚠ **The seat exists and has run four times.** It is an agent in this office with no Docker of its own; it drives `h-lab` over the shared SSH key, which is why the row's premise — *lanes have no Docker* — turned out not to be the blocker. ⚠ **It has never caught a regression, and has been worth it anyway**: it found four stranded networks on its first assignment, established the baseline every later failure is attributed against, proved acceptance never invokes `office usage` or `office status`, produced the coverage table showing pause and resume have never run, measured the reconciliation gap at 4.091 s, and its lab findings became a `BUILD-CONVENTION` rule. ⚠ **Its most valuable output is consistently what it CANNOT reach** — it has named that unprompted in every run. The original: | Everything above was found by an operator, not by a lane or by me. Lanes have no Docker and cannot run what they build; the architect writes the specs and then checks his own work. ⚠ **`flow-check.py` is the floor, not the answer** — a script catches regressions, it does not notice an agent quietly asking for permission |
| ~~**nothing says what a run costs**~~ **— SHIPPED in build 82** | ⚠ **`office usage` exists**, reading the `usage` records the watchdog emits from the CLI session files `ActivityTailer` already tails. Four token buckets, longest-prefix pricing from `container/config/pricing.json`, and a model with no entry reads `unpriced` rather than `0.00`. ⚠ **Spend also joins to a conversation**: the first usage record after a delivery marker carries that envelope's `stream_id` and `correlation_id` — measured live, 18 of 27 attributed. ⚠ **What is still open**: attribution loss is silent, because `delivery.markers` is bounded at 500 and a trimmed marker produces an unattributed record with no signal. The original entry: | h-office carried `usage.py` and a `pricing.json` and could answer "what did that sprint cost". h-flock has **no cost surface at all** — not per agent, not per tenant, not per run. ⚠ **It matters most exactly where h-flock is strongest**: four agents on a vendor CLI for five hours is the normal shape of a build here, and the operator finds out from a billing page afterwards. A local provider makes it free and the number uninteresting; a vendor one makes it the first question. **Port shape is known and small** — the h-office files are the reference |
| ~~**every sign-off so far was signed by its own author**~~ **— ARRANGEMENT SET 2026-08-23** | ⚠ **The verifier is ASSIGNED by the architect and never sourced by the author.** That rule exists because it was broken once: `tmux` sourced `api` while the assigned verifier had the ticket in `doing`, producing a reciprocal pair inside one round — `tmux` had verified `api`'s build 88, `api` then verified `tmux`'s 91. Both lanes acknowledged it immediately and it has not recurred. ⚠ **With four lanes, at most TWO may author if the other two are to verify** — that, not merge contention, is what the two-in-flight rule was always about. ⚠ **It works because refusals are real**: build 91 was refused five times, build 93 twice, builds 92, 95 and 96 once each, and **four of build 91's five findings were against the architect's contract rather than the lane's code.** The original: | ⚠ **Builds 80, 81 and 82 all carry `author of the change? NO`** — the first independent signatures in this repository. `tmux` refused build 82 six times, each at a real locus. ⚠ **But nothing makes that happen.** It exists because I wrote *"VERIFIED BY is not you"* into three build specs by hand and withheld merges; no agent is told to review anyone and no check fails. ⚠ **And it does NOT belong in the framework** — h-flock sets an office up, it does not direct how agents work. This is an operator arrangement, recorded here so it is chosen rather than drifted into. The original: | `TEST-SIGNOFF` ends with `VERIFIED BY <lane> — author of the change? YES\|NO`, and **every gate in this repository to date says `architect` and `YES`**. The field was added because BUILD 77 shipped two defects that `api` found on first independent read. ⚠ **A field that records the problem without preventing it is not a control.** The three lanes independently proposed a **rotating attacker chosen before implementation** rather than a permanent adversary seat; nothing has been set up to do that. **The arrangement half is the operator's to set, not mine** |
| **`CLAUDE_CODE_OAUTH_TOKEN`** ⚠ *AUTHENTICATION PROVEN 2026-08-23 — only precedence is open* | ⚠ **The token authenticates.** Measured on a tenant with **no seeded credentials**: 54 usage records against `claude-sonnet-5`. ⚠ **And this office runs on it** — the acceptance seat's profile has no `.credentials.json` at all, so every acceptance run today was performed by a token-authenticated agent. ⚠ **The watchdog half shipped in build 91**: a token-authenticated agent no longer alerts `absent` forever, at the cost recorded in its own row above — a **revoked** token is now invisible. ⚠ **What is actually still open is PRECEDENCE**: when a profile has both a token and a seeded `.credentials.json`, which wins? A live banner suggested the token does, which is not proof. It decides one sentence of help text. The original: | ⚠ **Built**: `setup.sh` asks per account with `read -rsp` so nothing is echoed, stores `CLAUDE_OAUTH_TOKEN_<PROFILE>` in `container/.env`, and preserves it across re-runs the way `API_TOKEN` already was — so re-running setup to add an agent no longer deletes it. `window_env` injects only the token matching that agent's profile, so two accounts never receive each other's credential and the profile decides both config dir and credential. Absent stays absent rather than becoming an empty string, which the CLI would read as a credential that fails. ⚠ **NOT verified**: nobody has confirmed the CLI accepts the token at all, nor what happens when a profile has BOTH a token and a seeded `.credentials.json` — that precedence decides whether a token replaces a login or only fills an absence, and it is one sentence of help text either way. ⚠ **Transport is the operator's problem and stays one**: however it arrives, the token rests in `.env` (mode 600, never in the image) and is readable from `/proc/<pid>/environ` by any agent, same as `API_TOKEN`. `scp` beats typing it; a silent prompt beats shell history | ⚠ **Unknown to h-flock today**: zero references in code or docs. Auth is a *file* — `seed-home.sh` `docker cp`s `.claude/.credentials.json`, `.codex/auth.json` and agy's OAuth token into a running tenant. ⚠ **A token turns that into configuration**, which closes *seeded credentials do not survive `--force-recreate`* outright and turns *profile logins* from one interactive browser login per account per rebuild into minting a token once. **Four integration points**: ask per account in `setup.sh`'s existing accounts branch; store per **profile** in Redis beside `provider` (`tmuxhost/host.py:53`) and **not** in `.env`, because `.env` reaches the tmux server and therefore every pane; inject per window where `ANTHROPIC_AUTH_TOKEN` already is (`tmux/ops.py:279`); and leave the file path untouched so both work. ⚠ **Two things bite.** `watchdog/service.py:264` tests for `.credentials.json`, so a token-authenticated agent alerts `status: absent` **forever** — and credential alerts never clear. And **precedence must be decided and written down**: `ops.py` already carries the scar *"a previous subscription's `ANTHROPIC_*` wins over what we set here"*. ⚠ **It buys correctness, not isolation** — every agent is uid `ubuntu`, so a per-window env var is readable from `/proc/<pid>/environ` by any peer. It guarantees the right agent uses the right account; it does not keep account A's token from agent B |
| ~~**`office send` cannot carry a real payload, and says nothing when it fails to**~~ **— SHIPPED in build 87** | ⚠ **`--stdin` and `--file` both exist**, mixing them with positional text is refused, empty stdin is refused, and the acknowledgement now reads `sent to NAME: N bytes (STREAM_ID)` — so an agent can see the body was carried. ⚠ **The root cause was one line**: `argparse.REMAINDER` is gone from `send`, which is why the `--agent=` row below died in the same edit. The body is now ONE argument; `--` carries a dash-leading one. ⚠ **The agent guide was changed in the merge, not left for later** — `tmux/ops.py` was still teaching the unquoted form that the new parser rejects. Verified live on h-lab: the three unquoted `office send` calls in `plumbing-check.sh` still pass, and no argparse error appears anywhere in an acceptance run (`BUILD-89-results`). The original: | ⚠ **Measured**: a codex agent with a multi-line report ran `office send -a architect --stdin`. `text` is `argparse.REMAINDER`, so the flag was not rejected — it became the body, and the agent sent the single word `--stdin`. **Six clean custody stages carrying the wrong content.** The send did not fail; it succeeded with the report missing. ⚠ **And the acknowledgement made it undetectable**: `send` returns a bare stream id, which confirms *enqueueing* and says nothing about recipient, byte count, truncation or delivery — so the agent had no way to learn the body was gone. Only a human reading the recipient's pane caught it. ⚠ **REMAINDER also means no flag on `send` is reachable, ever**; every mistyped flag silently becomes message text. Wanted: `--stdin` and `--file`, refusal when mixed with positional text, refusal of empty stdin, and an acknowledgement carrying bytes accepted. Independently raised by all three agents — one hit it, one read the parser, one traced the source |
| ~~**`office send --agent=NAME` is rejected with a message that does not say why**~~ **— SHIPPED in build 87** | ⚠ **Died with the `REMAINDER` that caused it.** The hand-rolled `argv[0] not in ("-a", "--agent")` check existed only because REMAINDER made real parsing impossible; with argparse doing the parsing, the equals form works like it does everywhere else. The original: | `-a bob` and `--agent bob` work; `--agent=bob` raises *"office send requires -a &lt;agent&gt;"*. The check is `argv[0] not in ("-a", "--agent")`, which cannot see the equals form argparse accepts everywhere else. ⚠ **Verified 2026-08-23.** Either accept it or say what is wrong with it |
| ~~**`--profile` is not validated against the accounts that exist**~~ **— SHIPPED in build 91** | ⚠ **Validated against what `setup.sh` configured**, seeded into Redis from the entrypoint, read by the office client and the fabric alike, with the error naming the accounts that exist. ⚠ **An absent key means DO NOT VALIDATE**, following `bus/policy.py`'s precedent, so a tenant created before this key keeps working. ⚠ **The first attempt read config DIRECTORIES and was wrong in both directions** — a token-only account was refused while a `mkdir`'d typo was accepted, so the artifact of the bug became proof the bug's input was valid. Caught by `bus` with an exact probe. The original: | `control/openers.py` validates the value as a **segment string**, not as a known account. ⚠ **Measured**: `--profile ACCOUNT_2` and `--profile 2` both dead-lettered with `opener failed: '2'` — a bare `KeyError` repr naming neither the problem nor the rule, arriving asynchronously one component away from where it was typed. ⚠ **And a *plausible* typo is worse**: `--profile typo` passes validation, `seedProfile` populates the directory, and the agent **starts cleanly against an account nobody configured**. `--cli` got `choices=` on 2026-08-23; this did not. Traced independently by an agent reading the source |
| **⚠ even at the DEFAULT delay, a burst produces a duplicate submission** ⚠⚠ *build 113, and duplicates are the one thing this design calls an absolute defect* | At `PASTE_ENTER_DELAY=0.5`, a 20-envelope burst lost nothing — **but `BURSTD001` was submitted TWICE**, once alone and once bundled with `BURSTD002`, and `BURSTD002` never got a standalone turn. ⚠ **The agent therefore acts on one message twice.** The fabric sent it once; the terminal submitted it twice, so no custody record shows it. ⚠ **`HLD` §10 makes at-most-once the property the whole design exists to hold**, and this is a duplicate arriving *below* the layer that guarantees it — the fabric's promise is intact and the agent's experience is not. ⚠ **Rate: one duplicate and one bundling in 20**, so roughly a tenth of a burst is not clean even with the mitigation. ⚠ **This is the shape of a multi-agent session** — several agents writing to one busy agent — and it means *"the agent ignored my message"* may be this rather than the model |
| **⚠⚠ back-to-back deliveries into one pane can coalesce or vanish — and the delivery lock does not cover it** ⚠ *seen during build 112 calibration, out of that ticket's scope, and directly relevant to a multi-agent session* | ⚠ **Measured**: five markers sent to one agent with genuine client-side concurrency — **two coalesced into a single submitted turn, and one (`BURSTZ003`) never appeared in the pane or any scrollback at all.** The same tenant, sent **sequentially**, delivered 50 of 50. ⚠ **A per-destination lock EXISTS** — `src/flock/port/deliver.py:183` acquires a `delivering` tag with `hsetnx` and spins until it wins, releasing at `:197`. **So the fabric already serialises concurrent deliveries.** ⚠⚠ **INFERENCE, NOT YET VERIFIED — the lock covers our WRITES, not the CLI's READS.** It is released once `paste_text` returns, which is when `send-keys` returns, **not** when the CLI has consumed the input. Two deliveries can therefore be written correctly in sequence and still be coalesced by a CLI that has not finished processing the first. ⚠ **If that inference holds, `ENTER_DELAY` is load-bearing for CONSECUTIVE messages rather than for a single one** — which would explain why build 112's sequential run found nothing at either setting: a full `office send` round trip between envelopes supplies the spacing the delay exists to guarantee. ⚠⚠ **This is the shape of a real multi-agent session**, where several agents message one agent and a lost message is invisible because `opened` fires regardless. **Verify the inference before drawing conclusions from build 112's clean result** |
| **⚠⚠ the delivery verification hop EXISTS, ran, and stayed silent for four real losses** ⚠ *build 113 — and build 81's fix for false positives is what blinded it* | ⚠ **The hop the port cannot provide is already built, one component over**: `pending.verify` and `delivery.markers` feed `src/flock/watchdog/verification.py`, which judges a paste against later CLI activity. **It ran during build 113 and emitted ZERO `delivery_unverified` records** while four messages were lost. ⚠ **It is not broken — it is an ALIVENESS check.** `verification.py:118` is `any(input_time > marker_time ...)`: did the CLI do *anything* after we pasted. ⚠⚠ **In a burst, the sixteen messages that DID arrive supply that aliveness for the four that did not.** It cannot distinguish *the CLI received my message* from *the CLI received a message.* ⚠ **And build 81 widened it deliberately** — it had fired on **1,180 of 1,285** deliveries, and the comment at `verification.py:111-114` names the resulting false positive in as many words: *"alive does not prove"* consumption. **Fixing the false positive created a false negative, and nobody had a real loss to test it against until now.** ⚠ **The fix shape is per-MARKER evidence rather than per-agent aliveness** — correlating one marker to one input event, which is exactly what the seat did by hand against the CLI's own transcript. ⚠⚠ **That is CLI-specific** — claude JSONL, codex rollout, agy SQLite — **the same wall build 88 hit on usage**, so it is bounded work with a known cost rather than an open question |
| **⚠⚠ nothing records the TERMINAL layer — six stages end at the port's handoff** ⚠ *build 113 measured a message vanishing below the last record, with every stage clean* | ⚠ **`opened` IS NOT WRONG, and an earlier version of this row said it was.** `opened` records that the port took custody and completed its delivery action — paste and Enter returning without error. **It counted 20 handoffs and 20 handoffs happened.** ⚠ **Stopping at the port boundary is correct**: h-flock is a switch, it forwards by name and never reads content, so whether the destination *application* consumed what it received is deliberately outside the fabric's knowledge. ⚠⚠ **The defect is `docs/CONTRACTS.md:347` claiming an `opened` record *"proves delivery"* without saying delivery TO WHAT** — and the gap is that **no record anywhere covers the layer below it.** ⚠⚠ **MEASURED 2026-08-24, and it is no longer an inference.** A 20-envelope burst into a paused-then-resumed agent produced **20 `opened` records and 16 markers in the CLI's own transcript**. Four — `BURSTZ003`, `BURSTZ004`, `BURSTZ010`, `BURSTZ018` — appear **nowhere**, confirmed by `comm -23` against the full set and re-checked independently: zero occurrences each. ⚠ **`opened` said 20 arrived. The CLI received 16.** That was at `PASTE_ENTER_DELAY=0`; at the default `0.5` nothing was lost. **The contract's claim is now disproven by measurement rather than doubted by reading.** `src/flock/tmux/ops.py:455-468` is `load-buffer`, `paste-buffer`, sleep, `send-keys Enter`, return. ⚠ **Nothing reads the pane** — there is no `capture-pane` anywhere in the delivery path. So `opened` means **tmux accepted four commands without error.** ⚠⚠ **`docs/CONTRACTS.md:347` says *"an `opened` record proves delivery"*, and `:351` uses that to settle a broadcast recipient as delivered — *"never reported as a known broadcast loss"*.** Meanwhile `docs/LLD-port-tmux.md:208` documents the exact counter-case: *"the Enter is swallowed, the message sits unsubmitted, and the agent looks idle."* **The two living documents contradict each other and build 92's indeterminate logic rests on the false one.** ⚠ **The honest split, and it is DEFENSIBLE rather than embarrassing**: `opened` proves the fabric completed handoff **to the terminal** — the characters are in the pane, `paste-buffer` succeeded. It does **not** prove the agent received the message, and consumption by a CLI is arguably beyond the fabric's boundary. **Conservation's use is fine once the contract says WHICH claim it is making.** ⚠ **This decides the README too**: *"none lost"* is true of the fabric and not of the agents, and that version is stronger because it survives someone checking. ⚠ **Same shape as build 91's `_accepted`, one layer down** — five refusals established that `_accepted` does not mean the window exists; `opened` not meaning the agent read it has been in the contract the whole time |
| **the stuck-agent alert cannot tell "finished but did not close the ticket" from "wedged mid-task"** ⚠ *the first watchdog alert to fire in a day of watching, 2026-08-24, and its conclusion was wrong* | The watchdog reported `tmux` *"on task for ~10m without finishing, no terminal output for 5m — likely stuck rather than slow"*, and presence read `wedged`. ⚠ **Everything it observed was true.** The ticket was in `doing`, output had stopped, the agent was idle. **The conclusion was false**: `tmux` had finished, pushed `e432158`, and been verified by `bus` twenty minutes earlier. It was between turns. ⚠⚠ **The distinguishing evidence existed and was not used — THE WORK WAS PUSHED.** A check of whether the ticket's deliverable had landed turns *"an agent is stuck"* into *"an agent is idle with an open ticket whose work is already done"*, and those call for opposite actions: one is a rescue, the other is bookkeeping. ⚠ **Same shape as `delivery_unverified` firing on 1,180 of 1,285 deliveries** because it could not tell a thinking agent from a wedged one — build 81 fixed that by widening what counts as alive. **This is that confusion moved up a layer, into presence and the board.** ⚠ **Cost is small and real**: one round trip, and a lead who now half-discounts the alert — which is exactly how a signal that fires on the normal case trains everyone to ignore it |
| **the task board has no push, so a lead counts by hand** ⚠ *the coordination role is by design; the bookkeeping is not* | ⚠ **A maintainer coordinating SMEs across separate modules is the intended shape**, and peer-to-peer messaging already exists — that is not the gap. The gap is mechanical: a ticket lands with **no notification**, so `AGENTS.md` instructs a manual `sendMessage` doorbell after every `jira add`, and in a real run the lead also hand-counted each agent's "N/10" message budget. ⚠ **Phase 2 of that run had no ticket at all**, so the debate was invisible on the board and unauditable afterwards. Wanted: assignment delivers itself, and phase work can carry a ticket per participant |
| **an agent can address a participant it cannot discover** ⚠ *found by `bus` probing a false premise the architect supplied, 2026-08-24* | `src/flock/office/cli.py:173` filters `office peers` to `port_type == "tmux"`, so an api client is **omitted entirely** rather than shown without a framework. ⚠ **This is deliberate and gated** — `container/plumbing-check.sh:150` and `:151` are acceptance checks named *peers hides client* and *peers really hides*. ⚠ **But an agent CAN send to it**: `container/plumbing-check.sh:160` has an agent message `telegram` successfully. **So a participant is addressable and undiscoverable at the same time**, and nothing anywhere argues why. ⚠ **It may well be right** — a client is an external application, not a colleague, and advertising it to agents invites them to treat it as one. **The gap is that the reasoning was never written down**, so the next person to look will read the filter as a bug and the two gates as protecting one. ⚠ **Decide and record it**; do not change it casually, because two acceptance gates depend on the current behaviour |
| ~~**an agent cannot tell what its peers are**~~ **— SHIPPED in build 108** | `office peers -v` reports **framework, profile and current task** per peer, built entirely from `launch`, `profile` and `tasks.doing` — keys the same file already read, so a display rather than a data path. ⚠ **Plain `office peers` is unchanged**, guarded by a test that asserts it stays unchanged **while the enriched state exists**, which is when a regression would actually happen. ⚠ **An agy peer reads `framework=agy`, not `unknown`** — the word already meant three things and this build declined to give it a fourth. ⚠ **Scheduled ahead of two specced builds** because the agents asked for it after the 2026-08-23 session and the agy agent raised it: four of them reasoned about each other for an hour with no idea what each other was. The original: | `office peers` returns names. Nothing says which framework a peer runs — yet claude, codex and agy differ in what they can do, and an agy peer cannot be pointed at a local model or priced at all. ⚠ **Every agent in the 2026-08-23 run reasoned about peers without knowing what they were.** Raised by the agy agent, which is the one that most needed it. `office peers -v` showing framework, profile and current task |
| **presence and cost are not comparable across CLIs** ⚠ *HALF SHIPPED in build 88 — read the three rows above before working this* | ⚠ **codex is fixed**: the model comes from `turn_context` per turn, so rows price instead of reading `unpriced`, and per-turn `last_token_usage` is used rather than cumulative `total`. ⚠ **agy is answered rather than fixed** — its state holds no token counts anywhere, so it is named **not measurable** in both `office status` and `office usage`, proven live against a real hired agy agent (`BUILD-90-results` part 2). ⚠ **What is still open has its own rows above**: `rate_limits` has never run against a live codex agent, and `office status` still says `unknown` in the column beside the one that was fixed. The original: | ⚠ **Measured in one tenant**: `office status` reported an agy agent `unknown — no activity feed` **while it was actively messaging** (`activity.py` parses claude and codex formats only); codex reported `model: unknown` so every codex row prices as `unpriced`, indistinguishable from a free local model; and agy contributed **zero** usage records despite being the most talkative peer. ⚠ **So the cost table invites a comparison it cannot support.** Either normalise per-CLI adapters or state plainly in the output which agents are not measurable |
| **`correlation_id` exists on every envelope and is invisible to agents** ⚠ *and build 108 found exactly WHY — the choke point does not hand it back* | ⚠ **`src/flock/bus/doors.py:43` returns `-> str`: a stream id, and nothing else.** So no caller can see the `correlation_id` the fabric minted — not `office send`, not the api door. `tmux` hit this while trying to add the id to `send`'s acknowledgement as a read-only convenience, and **correctly dropped the rider rather than widening a contract inside a build with a deadline.** ⚠ **This makes the deferred threading work concrete: the first task is not a CLI flag, it is WIDENING `send`'s RETURN.** ⚠ **And that is bounded** — `send` is the single choke point onto the bus with exactly two callers, the office CLI and the api door, which is the property the design already relies on for the policy check. Change the return once and both surfaces gain it. The original: | Agents asked for `--thread` / `--reply-to` / sequence numbers to keep a multi-party debate straight, and had to establish topology socially instead. ⚠ **The fabric already mints and propagates `correlation_id`** through every custody stage — it is the join key the whole log is built on. `office send` neither shows it nor accepts one, so a thread is reconstructible from the custody log and not from the interface an agent actually uses |
| **the framework cannot see the SSH access its agents depend on** ⚠ *raised by an agent, and true* | Shared `~/.ssh/config` and a shared key are what let agents reach other hosts, and they are entirely outside the fabric's visibility: nothing enrols them, nothing checks them, and **if they break, no office or flock record will show it** — the symptom is an agent that cannot do its task for reasons the log cannot explain. Also worth stating plainly somewhere: workspaces are ownership-isolated while host credentials are shared, so per-agent audit attribution does not exist |
| ~~**command naming is inconsistent**~~ **— SHIPPED in build 87** | `let-go` and `clone-to-all` exist; `letGo` and `cloneToAll` still work. The original: | `letGo` and `cloneToAll` are camelCase while every other verb is lowercase, and shell CLIs conventionally use kebab-case. Aliases would cost nothing and remove a class of guess |
| ~~**a hire leaves no record of whether it worked**~~ **— FULLY SHIPPED, build 91 then build 103** | Build 91 gave control four honest outcomes; build 103 joined `window_created` to its cause. ⚠ **Both halves took refusals to get right** — five on 91, two on 103 — and every one was about a record claiming more than it could know. The question *did that hire work* is now answerable from the log. The original: | ⚠ **Control now records what it can observe**: `{start,stop,pause,resume}_agent_{accepted,incomplete,failed}` via a decorator, so a fifth kind cannot silently forget. ⚠ **`_accepted` deliberately does NOT mean the hire worked** — it means every desired-state write was acknowledged, and actual state is applied asynchronously by `tmuxhost.reconcile_once`. **That half is a separate row and is not closed.** ⚠ **Five refusals, four of them against the architect's contract rather than the code**, produced the rule now in `BUILD-91` ruling 11: acknowledged is a fact, UNKNOWN is an attempt with no reply, and `failed` is reserved for not attempted or provably rejected. The original: | `src/flock/control/openers.py` contains **no `log_record` or `emit` call at all**. `StartAgent`, `StopAgent`, `PauseAgent` and `ResumeAgent` take custody and never say what they did, so an envelope to `host` shows the six transport stages ending in `opened` and then nothing. ⚠ **Measured**: two envelopes `architect -> host`, all six stages clean, and the only way to learn whether an agent had been created was to attach to a pane. ⚠ **`AddTicket` already does this right** — `port/openers.py:211` emits `board_write_confirmed` — so the pattern exists and the control kinds are the exception. ⚠ **And `LLD-bus-and-switch` states the contract as *"each component records that it took custody and what it then did"***, which these do not. A confirmation per control kind, naming the agent and the outcome, is the whole fix |
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
