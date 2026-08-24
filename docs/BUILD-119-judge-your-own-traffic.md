# Build 119 — the harness must judge only its own traffic

**Lane: `bus`. Base: `main` at `d22f93d`.** Found by `acceptance` in `BUILD-118`.

## The defect

`judge()` reads **every** JSON line in `docker logs` and buckets it by event with
**no filter for its own participants**, then:

```py
stray = sorted(set(opened) - set(sent))
```

⚠ So **any** envelope on the tenant with an `opened` record and no `sent` record
in the log is reported as a stray — **including traffic the harness never sent.**

**Observed live in `BUILD-118`:** four strays, every one `source=architect` to
`sme-2`/`telegram` — **real `accept.sh` plumbing-check traffic.** `office send`
issued inside a tmux pane writes its `sent` line to the **`docker exec` session's
stdout, not PID 1**, so `docker logs` holds the `opened` and never the `sent`.
⚠ **That is the exec-vs-logs boundary `BUILD-CONVENTION` §3.0 already documents,
appearing here as a false stray rather than a missing line.**

⚠⚠ **Consequence: the harness cannot run on a tenant that has any other traffic.**
It silently requires an idle tenant, and nothing says so. Both modes returned
`rc=3` while the harness's own accounting was **completely clean** — 20 sent in
steady, 220 cumulative by end of burst, zero missing, zero duplicated.

## The fix

**Scope `judge()` to the harness's own participants** — the `bench-` prefix it
already uses (`bench-port --prefix bench-`). Reconcile within that set only.

⚠ **This must NOT weaken the gate, and that is the part to get right.** A genuine
stray *inside the harness's own traffic* — an `opened` for a `bench-*` destination
that no `bench-*` sender sent — **must still be caught and still return `3`.**
Filtering the universe is not the same as forgiving what is in it.

⚠ **Prove both halves:** a run alongside unrelated office traffic returns `0`, and
an injected stray **within** `bench-*` still returns `3`. **The second is the one
that matters** — without it you have deleted a gate rather than scoped one.

⚠ **State the scope in the output**, so a reader knows what was judged and what
was ignored. A judge that silently narrows its universe is how we get a green run
that means nothing.

## ⚠⚠ The pattern this is the third instance of — read before designing the fix

| | what it judged | what it should have judged |
|---|---|---|
| `delivery_unverified` | flags **raised** | flags that **should have been** raised |
| the burst RED | envelopes **at capture time** | envelopes **after the queues drained** |
| this | **every** envelope on the tenant | **its own** envelopes |

⚠⚠ **Each one judged everything it could see and called what it did not
understand a defect.** All three produced a confident red on a healthy system.
**A judge must state its universe and judge only inside it.**

## Out of scope

⚠ **Do not fix the exec-vs-logs boundary** — it is documented, the harness's own
senders already redirect to `/proc/1/fd/1`, and scoping makes it irrelevant here.
⚠ **Do not wire anything into `accept.sh`.** ⚠ **Do not re-run acceptance.**

## Done means

Pushed, both halves demonstrated, `TEST-SIGNOFF`. ⚠ **Scan evidence for secrets
before pushing** — `ps -ef` carries argv and the denylist covers only `Config.Env`.
