"""The stable bus library surface, loaded without eager subsystem coupling."""

from importlib import import_module

_EXPORTS = {
    "available_profiles": ("accounts", "available_profiles"),
    "DeadLetter": ("doors", "DeadLetter"), "receive": ("doors", "receive"), "send": ("doors", "send"),
    "EnvelopeError": ("envelope", "EnvelopeError"), "build": ("envelope", "build"),
    "encode": ("envelope", "encode"), "parse": ("envelope", "parse"),
    "RESERVED": ("keys", "RESERVED"), "SEGMENT_REGEX": ("keys", "SEGMENT_REGEX"), "prefix": ("keys", "prefix"),
    "emit": ("logging", "emit"), "log_record": ("logging", "log_record"),
    "mirror": ("logging", "mirror"), "record_task_event": ("logging", "record_task_event"),
    "allows": ("policy", "allows"), "require_allowed": ("policy", "require_allowed"), "tags_key": ("policy", "tags_key"),
    "is_member": ("roster", "is_member"), "members": ("roster", "members"), "port_type": ("roster", "port_type"),
    "AGENT_DATA_RESOURCES": ("resources", "AGENT_DATA_RESOURCES"), "AGENT_STATE_RESOURCES": ("resources", "AGENT_STATE_RESOURCES"),
    "DURABLE_DATA_RESOURCES": ("resources", "DURABLE_DATA_RESOURCES"), "DYNAMIC_RESOURCE_PATTERNS": ("resources", "DYNAMIC_RESOURCE_PATTERNS"),
    "PER_AGENT_RESOURCES": ("resources", "PER_AGENT_RESOURCES"), "TENANT_RESOURCES": ("resources", "TENANT_RESOURCES"),
    "TRANSPORT_QUEUE_RESOURCES": ("resources", "TRANSPORT_QUEUE_RESOURCES"),
    "purge_agent": ("resources", "purge_agent"), "purge_transport": ("resources", "purge_transport"),
}

__all__ = list(_EXPORTS)

def __getattr__(name: str):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(f"{__name__}.{module_name}"), attribute)
    globals()[name] = value
    return value

def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
