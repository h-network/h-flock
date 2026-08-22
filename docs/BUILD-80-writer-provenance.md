# BUILD 80 — a custody record says who wrote it

**Base: `main` at `39b7545`.** Branch `bus/writer-provenance`.

## 1. The problem, demonstrated

On 2026-08-18, as unprivileged `ubuntu` inside a live tenant:

```bash
echo '{"module":"switch","event":"forwarded","stream_id":"FORGED-BY-AN-AGENT"}' >> /proc/1/fd/1
```

It landed in `docker logs`, and `analyse-run.py` counts it.

⚠ **This ticket is NOT about stopping that.** The interior of a tenant is open by
design — agents are colleagues who were hired (`HLD` §10). Closing that path
means uid separation and per-writer volumes, which is a different product.

⚠ **It is about the accident, which happens on every benchmark run.**
`container/scenarios/bench-port.py` and `bench-send.py` write custody records
into the same stream **by design**. A synthetic record and a real one are
byte-indistinguishable today, so:

- every conservation count includes synthetic traffic unless someone remembers
- a benchmark left running silently corrupts the next run's analysis
- after build 78's forgery there is no way to answer *"was this record real?"*
  except by trusting that nobody ran anything

## 2. What to build

**A `writer` field on every record**, naming the process that produced it.

```
{"ts":"…","module":"switch","event":"forwarded","writer":"switch","stream_id":"…"}
{"ts":"…","module":"port","event":"sent","writer":"bench-send","stream_id":"…"}
```

### 2.1 Where it comes from

`FLOCK_WRITER`, read once in `bus/logging.py`. Default when unset: the existing
`module` value, so **every current record keeps its present meaning** and nothing
downstream breaks on day one.

The two bench scripts set `FLOCK_WRITER=bench-send` / `bench-port` for
themselves. Nothing else sets it.

### 2.2 Where it must appear

Every path that reaches the evidence file — all four found in build 79:

| site | writer |
|---|---|
| `bus/logging.py` `log_record` | `FLOCK_WRITER` or `module` |
| `watchdog/service.py` `_alert`, `_error` | `watchdog` |
| `switch/windowlog.py` re-emit | ⚠ **see 2.3** |
| `session/app.py` close record | `session` |

### 2.3 ⚠ The tailer is the hard case, and the reason this needs care

`WindowLogTailer` re-emits a line an **agent's process** wrote. The writer is the
agent, not the switch. **Do not overwrite a `writer` that is already present** —
re-stamping it `switch` would destroy exactly the provenance this ticket adds.
If the line has no `writer`, add `writer: "window:<agent>"`; if it has one, pass
it through untouched.

A test must cover both arms.

## 3. Analysis

`container/scenarios/analyse-run.py` gains `--writer` (repeatable) and
`--exclude-writer`. **Default behaviour is unchanged** — no flag means count
everything, so no existing invocation changes meaning.

Print the writer census in the summary, always:

```
writers: switch=4211  port=4211  bench-send=200  window:architect=17
```

⚠ **A run whose census contains a bench writer and was reported as a measurement
is a REFUSED sign-off.** Say so in the summary line, do not just print it.

## 4. Verification — required, per `TEST-SIGNOFF`

Three controls, each failing at a **named locus**:

1. **absent `FLOCK_WRITER`** → `writer == module` for every record; the census
   matches a pre-change run exactly
2. **`FLOCK_WRITER=bench-send`** → those records carry it, and
   `--exclude-writer bench-send` removes exactly them and nothing else
3. **a line that already has `writer`** through the tailer → the value survives;
   mutate the tailer to overwrite and this test must fail **in the tailer**, not
   in the census

Plus: the build-79 regression guard
(`test_no_json_record_reaches_stdout_without_the_mirror`) must still pass.

## 5. Out of scope — do not build

- signing, HMAC, or any attempt to make `writer` unforgeable. It is a **label,
  not a credential**, and h-vab measured the alternative and declined it
  (`COMPARISON-hvab-fabric` §3.1). Writing it as if it were trustworthy is worse
  than not having it.
- uid separation, per-writer volumes, Redis ACLs
- changing any existing event name or record shape beyond adding the one key

## 6. Done means

Pushed to `origin`, `python3 -m pytest -q` green, `python3 tools/check_citations.py`
exit 0 read **unpiped**, and a filled `TEST-SIGNOFF` block in
`docs/BUILD-80-results.md` with the three controls above and their observed loci.

⚠ **`VERIFIED BY` is not you.** Ask `api` or `tmux` to read it — every sign-off
in this repository so far says `author? YES`, and that is the open finding this
build should not add to.
