# Port delivery: transient runner, registry, and handlers

This note describes the current implementation. It uses “continuous” only for
code that owns a long-lived loop. A function can wait for a lock, drain a queue,
make network calls, or launch subprocesses without becoming a daemon: the
important distinction is whether it remains alive waiting for future work or
runs only because a caller supplied one delivery kick.

## There is no port-delivery daemon

Nothing in `src/flock/port/` runs continuously.

`src/flock/port/__main__.py` is the transient inbound entry point. The switch
starts one `flock.port <agent>` process for a delivery kick. `main()` restores a
waitable `SIGCHLD` disposition, reads the destination and tenant connection
settings, calls `run_port()`, and exits.

`run_port()` in `src/flock/port/deliver.py` owns the per-kick lifecycle:

- It constructs a Redis client.
- It waits until `HSETNX` acquires the destination's entry in the tenant-wide
  `delivering` hash.
- It calls `deliver_one()` once.
- It removes the busy tag in `finally` and returns.

The lock-acquisition `while` loop can wait forever behind a stale tag, but it is
not a service loop. It waits to finish one already-requested delivery and never
looks for a second destination or a future kick. Likewise, `drain_ingress()`'s
fallback `LPOP` loop drains the queue visible to one invocation; the normal path
uses one atomic Lua snapshot. Neither path polls for future envelopes.

`src/flock/port/send.py` is also caller-driven, but it is the opposite side of
the fabric. Its CLI builds one outbound envelope through `flock.bus.send` and
exits. It is packaged under `flock.port`, but it does not participate in the
inbound registry, lock, or handler dispatch.

## The generic inbound framework

The transport-neutral receiving path is split between the registry and the
dispatcher.

`src/flock/port/registry.py` contains:

- `_DEFAULT_REGISTRY`, the built-in mapping from `port_type` to lazy handler
  specification: tmux, API, control, and OpenShell.
- `get_delivery_handler()`, which resolves a callable for the selected type.
- `register_port_type()` and `unregister_port_type()`, which mutate the
  process-local registry for extensions.
- `reset_registry()`, primarily useful for tests and callers that need to
  restore the built-ins.

The default tuples preserve dependency boundaries. Looking up tmux imports
`flock.tmux.deliver`; control imports `flock.control.runner`; OpenShell imports
`flock.port.openshell`. The tuple remains stored, so each later lookup resolves
it again through Python's module cache. A custom tuple is resolved once at
registration to validate it and is then retained in the same form.

The registry itself has no discovery loop, configuration-file loader, or plugin
bootstrap. Its mutations affect only the current Python process. Since the
normal `flock.port` process is transient, an extension must arrange to register
inside that process before `deliver_one()` performs its lookup; registration in
some other process does not persist a new port type globally.

`src/flock/port/deliver.py` contains the generic mechanics:

- `run_port()` owns one busy-tag-protected invocation.
- `deliver_one()` checks the generic paused marker, reads the destination's
  current `port_type` from the roster, resolves the registered handler, and
  invokes it with only `r`, `pod`, `tenant`, and `agent`.
- `drain_ingress()` implements the atomic snapshot primitive shared by the
  batch-consuming handlers.
- `deliver_unroutable()` is the generic failure handler for absent, unknown, or
  unavailable handler mappings. It drains, parses when possible, and moves the
  raw envelopes to the destination's dead-letter list.

This path deliberately knows no tmux session, socket, sandbox, or API client
configuration. Each selected handler resolves its own transport state.

## Shared actions and schema

`src/flock/port/openers.py` is small after the tmux module split. It contains
two kinds of shared material:

- `add_ticket_opener()` validates and writes an `AddTicket` payload to the
  recipient's board, records the task event, and records whether the Redis write
  was confirmed, rejected, or had an unknown outcome. Both tmux and OpenShell
  delivery call it. It performs no terminal or sandbox operation.
- `ATTACHMENT_MAX_BYTES`, `ATTACHMENT_MAX_BASE64_CHARS`,
  `BASE64_CHARS_REGEX`, and `MIME_TYPE_REGEX` define attachment validation
  limits shared by the tmux and OpenShell attachment implementations.

The file name `openers.py` therefore describes only one function and does not
describe the constants. It is shared because of cross-handler reuse, not
because it is the generic dispatch contract.

## Port-specific handlers

The registry selects handlers with a common call shape, but their consumption
and side effects are intentionally port-specific.

### API mailbox delivery

`deliver_api()` still lives in `src/flock/port/deliver.py`. It snapshot-drains
ingress, parses each envelope, emits `received`, appends the normalized envelope
to the participant's bounded `inbox` stream, and emits `opened`. Malformed
envelopes go to the dead-letter list. It is an API-specific handler located in
the generic dispatcher module, not generic delivery behavior.

### OpenShell delivery

`src/flock/port/openshell.py` is a complete OpenShell-specific delivery
adapter. `deliver_openshell()` drains and parses a snapshot, resolves the
participant's CLI/profile and sandbox identity, then handles:

- `Message` and `Command` through a synchronous headless sandbox execution and
  an outbound bus reply;
- `AddTicket` through the shared board action;
- `Attachment` through OpenShell-specific validation, sandbox file creation,
  headless notification, and reply.

The module also owns OpenShell credential injection and cleanup. None of those
operations are part of the generic dispatcher even though the file currently
lives below `flock.port`.

### Tmux and control

Tmux delivery no longer lives under `flock.port`. The registry lazily selects
`flock.tmux.deliver.deliver_tmux`, whose terminal handlers live in
`flock.tmux.openers`. It imports the generic ingress snapshot and shared board
action, not the other way around.

Control delivery lives in `flock.control.runner.deliver_one`. It is the
intentional consumption exception: it receives at most one lifecycle envelope
per kick rather than calling `drain_ingress()`. Its lifecycle actions are
backend-specific and are not supplied by the delivery registry.

## Things that do not fit cleanly

`flock.port` names both directions. `send.py` is an outbound agent CLI, while
`__main__.py`, `deliver.py`, and `registry.py` form the inbound receiving edge.
Calling both a “port” reflects the network analogy, but it obscures which side
owns ingress serialization and which side merely submits to egress.

`deliver.py` mixes generic dispatch with the API-specific mailbox handler. API
delivery is lightweight and already imported with the generic package, but its
mailbox stream, JSON normalization, and `MAXLEN ~ 1000` policy are no more
generic than terminal paste or sandbox execution.

`openshell.py` sits under the generic package even though it is wholly a
transport adapter. This is historical placement, not a statement that sandbox
credentials, filesystem layout, or headless execution belong to every port
type.

`openers.py` combines a shared state mutation with attachment wire constants.
The AddTicket operation acts on a participant board rather than a transport;
the constants are schema, not actions. Their only common property is that two
delivery adapters import them.

`src/flock/port/__init__.py` is both the current generic public surface and a
compatibility surface. It directly exports generic functions and
`add_ticket_opener`, but its lazy `__getattr__()` also preserves the former
tmux-specific top-level attributes. The shim avoids eager tmux imports, yet a
reader of `flock.port.__all__` still sees transport-specific names in a package
described as generic.

The registry is extensible only within one process, while the roster is shared
state. A roster row can name a custom type that another transient port process
has never registered. The API shape suggests a system-wide plugin registry more
strongly than the implementation provides.

Finally, “delivery handler” does not imply one queue-consumption policy. Tmux,
API, OpenShell, and unroutable handling snapshot-drain; control receives one.
The real generic contract is access to Redis plus destination identity, not
batching, parsing, or a required `opened` outcome.

## A cleaner split and vocabulary

With freedom to reorganize the code, I would separate the transient runner,
generic routing, shared domain actions, and concrete adapters:

- `flock.delivery.main`: the `flock.port <agent>` executable entry point.
- `flock.delivery.runner.run_delivery_kick()`: Redis construction, busy-tag
  acquisition, one dispatch, and release. This replaces `run_port()`, whose
  name does not say that it handles exactly one kick.
- `flock.delivery.dispatch.dispatch_ingress()`: pause check, roster lookup, and
  handler invocation. This replaces `deliver_one()`, which sounds like it
  consumes one envelope even though most handlers drain a snapshot.
- `flock.delivery.registry`: the handler specifications and lookup API. I would
  call entries `DeliveryAdapterSpec` rather than `HandlerSpec`, making clear
  that they select a receiving medium, not an envelope-kind callback.
- `flock.delivery.ingress.snapshot_ingress()`: the Lua/fallback queue
  primitive, replacing `drain_ingress()` with a name that exposes the atomic
  boundary rather than only the end state.
- `flock.delivery.dead_letter.dead_letter_unroutable()`: the current
  `deliver_unroutable()`, named for its guaranteed outcome.
- `flock.api.delivery.deliver_mailbox()`: the current `deliver_api()`, moved
  beside the API mailbox contract and named for what it actually writes.
- `flock.openshell.delivery`: the current `flock.port.openshell` adapter,
  beside the OpenShell client, naming, and headless-command modules.
- `flock.board.delivery.add_ticket()`: the shared board mutation. “Opener” is
  unnecessary because this function neither opens a transport nor belongs to
  one.
- `flock.envelope.attachment_schema`: shared attachment limits and validators.
  The two concrete attachment handlers should call shared validation functions,
  not merely import regexes and duplicate the validation sequence.
- `flock.bus.cli.send`: the current outbound `flock.port.send` command, clearly
  separated from inbound delivery.

I would keep tmux and control in their present owning packages. The delivery
registry should point to adapter modules without pulling those adapters back
under a generic namespace.

For true extension support, I would replace process-local mutation as the main
mechanism with an explicit startup/plugin-loading contract. A persistent
configuration would map `port_type` names to import specs, and each transient
runner would load and validate that configuration before dispatch. If only
built-ins are intended, I would instead remove the public registration API and
call the mapping what it is: a fixed adapter table with test overrides.

The central boundary would then be: the switch creates a kick; the transient
delivery runner serializes one destination and selects an adapter; each adapter
owns its queue-consumption and transport semantics; shared board and envelope
schema code remain independent domain libraries. None of these components is a
daemon.
