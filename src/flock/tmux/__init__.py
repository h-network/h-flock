"""flock.tmux shared library for window and buffer operations."""

from .ops import (
    AmbientTmuxError,
    create_window,
    ensure_claude_project_trusted,
    generate_agents_md,
    kill_window,
    list_windows,
    paste_text,
    require_isolated_tmux,
    run_tmux,
    write_agent_guide,
)

__all__ = [
    "AmbientTmuxError",
    "require_isolated_tmux",
    "create_window",
    "kill_window",
    "list_windows",
    "paste_text",
    "run_tmux",
    "generate_agents_md",
    "ensure_claude_project_trusted",
    "write_agent_guide",
]
