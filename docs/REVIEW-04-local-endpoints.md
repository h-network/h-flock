# Review 04 — running an agent on a local model

> What was built, what was measured, and what is still only reasoned. An agent
> can now run against a local inference server instead of the vendor's API.

## 1. What it is

An agent may be pointed at a model endpoint. Everything downstream is unchanged —
same window, same paste, same activity file, same presence, same verification.
h-flock does not talk to the model; the CLI does.

```json
{"kind":"StartAgent","payload":{"agent":"lab","vab":"tmux","cli":"claude","endpoint":"local"}}
```

| | |
|---|---|
| per agent | `<prefix>:agent:<name>:endpoint` — a **name**, nothing else |
| per tenant | `ENDPOINT_<NAME>_URL` / `_MODEL` / `_TOKEN` / `_SMALL_MODEL` / `_KIND` |
| installer | `setup.sh` asks, probes, and writes both |

⚠ **The name is per agent; the address is tenant configuration.** A url in a Redis
value would be an endpoint an agent could read and change, and the roster holds
membership and VAB, nothing else.

⚠ **Such an agent uses no account credential.** No login, and the watchdog's
credential check does not apply to it. A missing login is not a fault for it.

## 2. The configuration claude actually needs

Supplied by the owner from a working setup, and every line of it earned:

- **all three tier variables, same id** — `ANTHROPIC_DEFAULT_OPUS_MODEL`,
  `_SONNET_MODEL`, `_HAIKU_MODEL`. claude picks a tier internally, so setting
  `ANTHROPIC_MODEL` alone leaves the others falling back to real Anthropic names
  the server does not serve. ⚠ **The failure reads as `issue with the selected
  model`, a model error for a configuration problem** — which is exactly the
  wrong thing to go chasing
- **no `/v1` on the base url** — claude appends `/v1/messages` itself. codex
  wants the opposite, which is how this gets copied in wrong
- **the id must match the served id byte for byte** — `gpt-oss:20b` is not
  `gpt-oss-20b`. The installer offers what `/v1/models` returns rather than
  asking anyone to type one
- **strip inherited `ANTHROPIC_*`** — a previous subscription's variables win
  over what we set, which is the quietest way for this to look broken
- **never pass `--model`** with a base url set; the tier variables decide

## 3. Measured on a live vLLM

`qwen3-vl-32b`, served by vLLM, reached from inside the tenant.

| | |
|---|---|
| plain answer | ✅ |
| single tool | ✅ `Listed 1 directory`, correct contents |
| multi-step tools | ✅ `Write` → `Read`, correct answer from the file |
| precise reading | ✅ 25 lines and a verbatim quote from line 22 |
| **office tooling** | ✅ `office send` to a colleague, delivered, colleague replied |
| activity feed | ✅ `input → tool: Bash → output` |
| presence, delivery, verification | ✅ identical to a cloud agent |

⚠ **Tool calls work**, so this vLLM has `--enable-auto-tool-choice` and a parser
matching the template. Without them a model emits literal `<tool_call>{…}</tool_call>`
text and the agent is useless for real work. That is server-side.

## 4. Two behaviours worth knowing

⚠ **Ghost text in the composer.** After each turn the pane shows a suggested next
prompt (`check the task board with office list`). It is Claude Code's suggestion
rendering, not input: a bare Enter does nothing and a paste replaces it. Measured
— it looks alarming in a screenshot and is harmless.

⚠ **It echoes.** Twice it repeated an incoming message back as its own output
before answering. Cosmetic.

## 5. What is NOT measured

⚠ **Long or large-context work.** This model has a 65k window against a cloud
model's 1M, and every test here was a short turn. A local agent will hit that
wall far sooner, and nothing here says what it does when it gets there.

⚠ **ollama.** The installer asks the type, falls back to `/api/tags` for model
listing, and warns when `/v1/messages` is absent — but no ollama was reachable to
test any of it. ⚠ **ollama does not serve the Anthropic Messages API**, so claude
cannot use one directly; it needs a translating proxy in front. Reasoned, not
run.

## 6. Two bugs this feature exposed

⚠ **`StartAgent` builds windows itself**, and only `tmuxhost` knew about
endpoints — so the first agent hired onto a local endpoint came up on the
vendor's. That path is not a fallback: `create_window` is idempotent by name, so
whatever it builds is what the agent keeps and a reconcile will not correct it.

⚠ **A probe with a made-up model id condemns a working endpoint.** vLLM answers
an unknown model with `404`, so the installer's capability check reported that a
functioning endpoint did not serve `/v1/messages`. It now probes with the id the
operator chose and reads the body: a `message` shape passes, an empty body means
the route is missing, anything else is shown verbatim.
