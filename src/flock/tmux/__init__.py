"""flock.tmux shared library for window and buffer operations."""

from .ops import (
    AmbientTmuxError,
    TmuxCommandError,
    create_window,
    ensure_agy_project_trusted,
    ensure_claude_project_trusted,
    ensure_codex_project_trusted,
    generate_agents_md,
    has_session_history,
    kill_window,
    list_windows,
    submit_text,
    require_isolated_tmux,
    run_tmux,
    start_agent_command,
    window_env,
    write_agent_guide,
)

_DELIVERY_EXPORTS = {
    "attachment_opener",
    "command_opener",
    "deliver_tmux",
    "mark_delivery_pending",
    "message_opener",
    "messages_opener",
}


def __getattr__(name: str):
    """Load delivery code only when its public attribute is requested."""
    if name not in _DELIVERY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if name == "deliver_tmux":
        from .deliver import deliver_tmux

        return deliver_tmux
    from . import handlers

    return getattr(handlers, name)

__all__ = [
    "AmbientTmuxError",
    "TmuxCommandError",
    "require_isolated_tmux",
    "create_window",
    "kill_window",
    "list_windows",
    "submit_text",
    "run_tmux",
    "generate_agents_md",
    "ensure_claude_project_trusted",
    "ensure_codex_project_trusted",
    "ensure_agy_project_trusted",
    "has_session_history",
    "start_agent_command",
    "window_env",
    "write_agent_guide",
    "deliver_tmux",
    "attachment_opener",
    "command_opener",
    "mark_delivery_pending",
    "message_opener",
    "messages_opener",
]
