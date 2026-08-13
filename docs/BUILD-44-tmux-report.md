# Build 44 — tmux documentation consistency report

Base: `main` at `564089f`.

Read in full: `LLD-tmux-host.md`, `LLD-adapter-tmux.md`, and
`LLD-container.md`. Compared their seams with `HLD.md` and `CONTRACTS.md`, and
checked description claims against the implementation where the documents
disagreed.

## Description contradictions corrected in owned documents

- `LLD-tmux-host.md:12-18` said one window per agent and that tmuxhost knew
  nothing about the bus, while its own `:129-132` limits windows to `vab: tmux`
  roster members and `src/flock/tmuxhost/host.py` reads roster and launch state.
  It now qualifies the window population and distinguishes roster/config reads
  from envelope transport.
- `LLD-tmux-host.md:23-26` said nobody attaches, while
  `LLD-container.md:188` and `flock.session` attach one control-mode client. It
  now says no *human* client is required and names the session attachment.
- `LLD-tmux-host.md:105-110` called the tmux socket directory an internal
  boundary, relaxing `HLD.md:340-343` (*the container is the boundary, and
  nothing inside it is*). It now describes owner-only mode as host-user
  protection and explicitly rejects agent-to-agent isolation.
- `LLD-tmux-host.md:147-152` and `LLD-container.md:172-176` gave
  `ROSTER_POLL_SECONDS` three consumers including the adapter, contradicting
  `LLD-adapter-tmux.md:96-101`. Code has only router and tmuxhost readers. Both
  owned claims now name those two readers.
- `LLD-adapter-tmux.md:16-36` placed the outgoing `office` command inside the
  adapter, contradicting `HLD.md:72,75` and the adapter's own per-delivery
  receive lifecycle. It now identifies `office` plus the bus library as the
  send side and the adapter as the receiving edge.
- `LLD-adapter-tmux.md:68-72` called the Redis backlog durable while
  `LLD-container.md:222-223` and `container/entrypoint.sh:107` disable all Redis
  persistence. It now states the exact guarantee: the queue survives adapter
  processes and is inspectable, but not persistent across tenant restart.
- `LLD-adapter-tmux.md:192-198` cited “HLD invariant 7,” contradicting the HLD's
  `:420-423` instruction to cite invariants by name because numbering drifts.
  It now cites *nothing in the data path reads a terminal* by name.
- `LLD-adapter-tmux.md:272-277` called pane reading and session endpoints
  deferred even though `flock.session` is built. It now distinguishes the still
  absent pane-to-bus path from the implemented, out-of-band human session path.
- `LLD-container.md:5-7,231-234` claimed the container owned no logic or
  decisions, contradicting its own `:70-110` exposure and certificate startup
  decisions. It now distinguishes deployment validation from domain logic.
- `LLD-container.md:193-196` said restart re-attached to existing state, while
  `LLD-container.md:222-223` says Redis state is lost and tmux also restarts. It
  now separates a repeated `compose up`/reconciliation pass from container
  restart and boot reconstruction.

## Contradictions in documents owned by other lanes

- `HLD.md:337-338` says there is one window “per agent,” while its participant
  table at `HLD.md:36-40` includes `api` and `control` agents and gives only
  `tmux` agents windows. Recommendation: say “one window per `vab: tmux`
  agent.” This is description, not a design fork.
- `HLD.md:79-80` says no non-library module imports another, while
  `CONTRACTS.md:203-208` and the implementation explicitly allow the adapter's
  lazy import of `flock.control`. Recommendation: name that exception in the
  HLD. This is description, not a design fork.
- `HLD.md:91-94` calls the in-Redis backlog a “durable queue,” while
  `LLD-container.md:222-223` deliberately disables persistence.
  Recommendation: qualify it as durable across adapter lifetimes, not tenant
  restarts. This is description, not a persistence design decision.
- `CONTRACTS.md:43-45` says adapter and other modules never import each other,
  but its own `:203-208` records the adapter→control exception.
  Recommendation: put the exception in the earlier absolute claim.
- `CONTRACTS.md:710` says `ROSTER_POLL_SECONDS` has three readers; only router
  and tmuxhost read it, and `LLD-adapter-tmux.md:96-101` explicitly says the
  adapter does not poll. Recommendation: change “three” to “two.”

No unresolved design-level contradiction was found in the three owned LLDs;
the contradictions above describe the built system and have code-decided
answers.
