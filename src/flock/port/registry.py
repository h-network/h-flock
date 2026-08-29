"""Registry for port_type delivery handlers."""

from __future__ import annotations

import importlib
import logging
from typing import Any, Callable, Dict, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Handler spec can be a direct callable or a lazy (module_path, attribute_name) tuple
HandlerSpec = Union[Callable[..., Any], Tuple[str, str]]

_DEFAULT_REGISTRY: Dict[str, HandlerSpec] = {
    "tmux": ("flock.port.deliver", "deliver_tmux"),
    "api": ("flock.port.deliver", "deliver_api"),
    "control": ("flock.control.runner", "deliver_one"),
    "openshell": ("flock.port.openshell", "deliver_openshell"),
}

_PORT_REGISTRY: Dict[str, HandlerSpec] = dict(_DEFAULT_REGISTRY)


def register_port_type(
    port_type_name: str,
    handler: HandlerSpec,
) -> None:
    """Register or override a delivery handler for a port_type.

    Lazy specs are resolved once here to reject invalid extensions at
    registration time, but the original spec is retained for lazy lookup.
    """
    resolved_handler = handler
    if isinstance(handler, tuple) and len(handler) == 2:
        module_path, attr_name = handler
        try:
            mod = importlib.import_module(module_path)
            resolved_handler = getattr(mod, attr_name)
        except (ImportError, AttributeError, TypeError) as exc:
            raise ValueError(
                f"invalid delivery handler for port_type {port_type_name!r}: "
                f"cannot resolve {module_path}.{attr_name}"
            ) from exc

    if not callable(resolved_handler):
        raise ValueError(
            f"invalid delivery handler for port_type {port_type_name!r}: "
            "handler must be callable or a resolvable (module_path, attribute_name) spec"
        )

    _PORT_REGISTRY[port_type_name] = handler


def unregister_port_type(port_type_name: str) -> None:
    """Remove a port_type from the registry."""
    _PORT_REGISTRY.pop(port_type_name, None)


def reset_registry() -> None:
    """Reset the registry to default built-in handlers."""
    global _PORT_REGISTRY
    _PORT_REGISTRY = dict(_DEFAULT_REGISTRY)


def get_delivery_handler(port_type_name: str) -> Optional[Callable[..., Any]]:
    """Look up and resolve the delivery handler for a given port_type.
    
    Resolves lazy (module_path, attr_name) specifications on every lookup.
    """
    if not port_type_name or port_type_name not in _PORT_REGISTRY:
        return None

    spec = _PORT_REGISTRY[port_type_name]
    if callable(spec):
        return spec

    if isinstance(spec, (tuple, list)) and len(spec) == 2:
        module_path, attr_name = spec
        try:
            mod = importlib.import_module(module_path)
            handler = getattr(mod, attr_name)
            if not callable(handler):
                logger.error(
                    "delivery handler %s.%s for port_type %r is not callable",
                    module_path,
                    attr_name,
                    port_type_name,
                )
                return None
            return handler
        except (ImportError, AttributeError) as exc:
            logger.error(
                "failed to import delivery handler %s.%s for port_type %r: %s",
                module_path,
                attr_name,
                port_type_name,
                exc,
            )
            return None

    return None
