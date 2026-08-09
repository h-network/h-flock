"""flock.tmux shared library for window and buffer operations."""

from .ops import (
    AmbientTmuxError,
    create_window,
    ensure_agy_project_trusted,
    ensure_claude_project_trusted,
    ensure_codex_project_trusted,
    generate_agents_md,
    kill_window,
    list_windows,
    paste_text,
    require_isolated_tmux,
    run_tmux,
    window_env,
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
    "ensure_codex_project_trusted",
    "ensure_agy_project_trusted",
    "window_env",
    "write_agent_guide",
]
