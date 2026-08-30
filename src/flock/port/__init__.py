"""Generic port delivery framework and shared delivery actions."""

from .openers import add_ticket_opener
from .deliver import deliver_api, deliver_one, deliver_unroutable, run_port
from .registry import get_delivery_handler, register_port_type, reset_registry, unregister_port_type


_MOVED_TMUX_EXPORTS = {
    "attachment_opener",
    "command_opener",
    "deliver_tmux",
    "message_opener",
    "messages_opener",
}


def __getattr__(name: str):
    """Lazily preserve old top-level tmux exports without eager tmux imports."""
    if name not in _MOVED_TMUX_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from flock.tmux import deliver as tmux_deliver
    from flock.tmux import handlers as tmux_handlers

    if name == "deliver_tmux":
        return tmux_deliver.deliver_tmux
    return getattr(tmux_handlers, name)

__all__ = [
    "add_ticket_opener",
    "attachment_opener",
    "command_opener",
    "deliver_api",
    "deliver_one",
    "deliver_tmux",
    "deliver_unroutable",
    "get_delivery_handler",
    "message_opener",
    "register_port_type",
    "reset_registry",
    "run_port",
    "unregister_port_type",
]
