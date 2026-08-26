# SPEC — local-model onboarding integration tool

An operator kicks this off with a vLLM endpoint. It stands up a tenant, hires an
architect and two SMEs against that endpoint, asks the architect to read
`AGENTS.md` and onboard the two SMEs, and captures what happened.

⚠ **This is a MANUAL INTEGRATION TOOL, like `tmux-nemotron.sh`. It must never be
wired into `accept.sh`'s suites.** A real model decides whether and how to
onboard anyone. That decision cannot gate a build, and a scenario that can fail
because a model chose differently is not a test — it is a coin toss with a
verdict attached.

## What it is actually for

Not "is the model good at onboarding". The question is narrower and answerable:
**when real agents run against a local endpoint and one of them tries to talk to
the others, does the plumbing carry it?** Everything this tool asserts is
delivery and logs. The model is the traffic generator, exactly as it is in
`tmux-nemotron`, where model agency is the coverage precisely because a model
produces content and timing nobody would hand-write.

## Variables

Reuse the existing provider convention. **Do not invent `VLLM_URL`.**

    PROVIDER_<NAME>_URL          required — the vLLM endpoint
    PROVIDER_<NAME>_MODEL        required — the served model id
    PROVIDER_<NAME>_TOKEN        optional
    PROVIDER_<NAME>_SMALL_MODEL  optional

    PROVIDER_NAME    which provider the three agents get     (default: local)
    TENANT           tenant name                              (required)
    POD              pod name                                 (default: acme)
    ARCHITECT        architect agent name                     (default: architect)
    SMES             two SME names, space separated           (default: "sme-1 sme-2")
    ONBOARD_TIMEOUT  seconds to wait for onboarding traffic   (default: 900)

Positional arg is an output directory, as `tmux-nemotron.sh` takes one.

⚠ **All three agents MUST be `claude`.** `startAgent codex` and `startAgent agy`
exit 3 when a provider is set — they refuse rather than silently running against
the vendor. Assert the CLI is claude at setup and REFUSE with 100 otherwise,
rather than discovering it as three dead windows.

## Two phases, two different kinds of verdict

**PHASE 1 — setup and plumbing. Asserted hard; may fail.**

Everything here is deterministic and a failure is a real defect:

1. The endpoint answers before anything is built. If it does not, `100` with
   the reason — an unreachable endpoint is not a product failure.
2. Tenant comes up; exactly one switch, one tmuxhost.
3. All three agents present in the roster with `port_type=tmux`.
4. Exactly one window each, named for the agent. Not two, not zero.
5. Each agent's `provider` key resolves, and the resolved URL matches
   `PROVIDER_<NAME>_URL`. This catches the case `setup.sh` used to print
   `(local)` for while the agent ran against the vendor.
6. ⚠ Credentials are NOT in the agent panes — reuse `tmux-boundary`'s prohibited
   set. An agent pointed at a local model uses no account credential, so this is
   the run where a leak would matter most.

**PHASE 2 — onboarding. OBSERVED. Never fails.**

Ask the architect, by ordinary delivery, to read `AGENTS.md` and onboard the two
SMEs. Then watch for **traffic**, not for quality:

- for each SME: did a message from the architect reach custody `opened`, and
  does the SME's pane contain the delivered text?
- scope by `stream_id` and destination. Never count a message from a previous
  run, and never let one SME's message satisfy the other's check.

## Output contract

⚠ **It emits `ONBOARDING`, never `RESULT`.** `accept.sh` says "each step prints
one `RESULT <step> <verdict>` line. Parse those" — so a `RESULT` line here could
be scraped and read as product health, which is the thing this tool must never
supply. `ONBOARDING` is invisible to that parser and legible to a person.

**The exit code is the contract; the line is for the operator.**

    ONBOARDING pass                              exit 0
    ONBOARDING incomplete reason=<why>           exit 100
    ONBOARDING fail failed=<n> reason=<why>      exit <n>

⚠ **`reason=` is REQUIRED on every non-pass.** A bare `100` cannot distinguish
an unreachable endpoint from a model that sat silent for fifteen minutes, and
those demand completely different responses from whoever ran it.

Mapping:

    both SMEs received architect traffic       -> pass, exit 0
    endpoint down / wrong CLI / no tenant      -> 100, before anything is built
    timeout, neither or only one SME reached   -> 100, reason=onboarding_not_observed
    phase-1 assertion failures                 -> exit the failed-check count
    a message was sent and DEAD-LETTERED       -> fail, that is a plumbing defect

⚠ **The distinction that makes this tool honest:** a model that never sends
anything is `100`, because nothing was proven either way. A model that sends
something the plumbing then loses is a `fail`, because that is our bug. Collapse
those two and the tool becomes worthless in both directions.

## Evidence

Retain regardless of outcome, into the output directory: resolved provider (URL
and model, **token redacted**), roster, window list, the custody records scoped
to this run's stream ids, and a capture of all three panes.

⚠ **Redact at capture time, not before reporting.** A token that reaches a file
has to be assumed compromised; redacting later only hides it from the reader.

⚠ **Evidence never enters the repo.** Output directory only.

## Tenant ownership and teardown

    KEEP    1 leaves the tenant running, 0 tears it down    (default: 1)

⚠ **It NEVER touches a tenant it did not create.** If `TENANT` already exists,
REFUSE with `100 reason=tenant_exists` rather than adopting it. An operator
running this must not be able to destroy an acceptance run that is mid-flight.

**`KEEP=1` is the default, deliberately against `accept.sh`'s convention.**
`accept.sh` is a gate and wants a clean lab afterwards; this tool exists so a
person can watch three agents work against their own hardware. Tearing down
automatically would delete the thing they ran it to see.

Two rails on that default:

- **Evidence is captured BEFORE any teardown, on every path**, so `KEEP=0` still
  leaves the record. A teardown that runs first turns a red run into an unreadable
  one.
- **Print the exact teardown command on exit, every time**, including on `KEEP=1`.
  A tenant nobody remembers how to remove is how the lab fills up.

## Explicitly out of scope

- Judging onboarding quality, or whether the architect read `AGENTS.md` "properly"
- Any assertion about model output content
- Running in `--core`, `--fault`, `--api`, `--tmux` or `--all`
- Emitting a `RESULT` line that a CI gate could consume as product health
