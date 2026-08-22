"""Model token pricing and cost calculations."""

import json
import os
from pathlib import Path

_CANDIDATE_PATHS = (
    Path("/app/container/config/pricing.json"),
    Path("/etc/flock/pricing.json"),
    Path(__file__).parents[3] / "container" / "config" / "pricing.json",
    Path(__file__).parents[4] / "container" / "config" / "pricing.json",
)

_FALLBACK_PRICING = {
    "claude-opus-4": {"input": 15.0, "cache_write": 18.75, "cache_read": 1.5, "output": 75.0},
    "claude-3-opus": {"input": 15.0, "cache_write": 18.75, "cache_read": 1.5, "output": 75.0},
    "claude-sonnet-4": {"input": 3.0, "cache_write": 3.75, "cache_read": 0.3, "output": 15.0},
    "claude-3-7-sonnet": {"input": 3.0, "cache_write": 3.75, "cache_read": 0.3, "output": 15.0},
    "claude-3-5-sonnet": {"input": 3.0, "cache_write": 3.75, "cache_read": 0.3, "output": 15.0},
    "claude-3-5-haiku": {"input": 0.8, "cache_write": 1.0, "cache_read": 0.08, "output": 4.0},
    "claude-3-haiku": {"input": 0.25, "cache_write": 0.30, "cache_read": 0.03, "output": 1.25},
    "gpt-5-codex": {"input": 2.5, "cache_write": 0.0, "cache_read": 1.25, "output": 10.0},
    "gpt-5": {"input": 2.5, "cache_write": 0.0, "cache_read": 1.25, "output": 10.0},
    "gpt-4o": {"input": 2.5, "cache_write": 0.0, "cache_read": 1.25, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "cache_write": 0.0, "cache_read": 0.075, "output": 0.60},
    "o1": {"input": 15.0, "cache_write": 0.0, "cache_read": 7.5, "output": 60.0},
    "o3-mini": {"input": 1.1, "cache_write": 0.0, "cache_read": 0.55, "output": 4.4},
}


def load_pricing(path: Path | str | None = None) -> dict[str, dict[str, float]]:
    """Load model pricing definitions from config file or fallback."""
    if path is not None:
        file_path = Path(path)
        if not file_path.is_file():
            raise FileNotFoundError(f"Pricing file specified but not found: {path}")
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"Pricing file contains invalid JSON: {path}") from exc

    env_path = os.environ.get("FLOCK_PRICING_FILE")
    if env_path:
        file_path = Path(env_path)
        if not file_path.is_file():
            raise FileNotFoundError(f"FLOCK_PRICING_FILE specified but not found: {env_path}")
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"FLOCK_PRICING_FILE contains invalid JSON: {env_path}") from exc

    for candidate in _CANDIDATE_PATHS:
        if candidate.is_file():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                pass

    return _FALLBACK_PRICING.copy()


def find_model_rates(model: str, pricing: dict[str, dict[str, float]]) -> dict[str, float] | None:
    """Find rates for model using longest-prefix match.

    Returns None if no matching key is found in pricing.
    """
    if not model or not pricing:
        return None
    matches = [key for key in pricing if model.startswith(key)]
    if not matches:
        return None
    best_key = max(matches, key=len)
    return pricing[best_key]


def calculate_cost(
    model: str,
    *,
    input_tokens: int,
    cache_read: int,
    cache_write: int,
    output_tokens: int,
    pricing: dict[str, dict[str, float]] | None = None,
) -> tuple[float | None, bool]:
    """Calculate token cost in USD using longest-prefix pricing rules.

    Returns (cost_usd, is_priced).
    If model has no match, returns (None, False).
    """
    if pricing is None:
        pricing = load_pricing()
    rates = find_model_rates(model, pricing)
    if rates is None:
        return None, False

    cost = (
        input_tokens * rates.get("input", 0.0)
        + cache_read * rates.get("cache_read", 0.0)
        + cache_write * rates.get("cache_write", 0.0)
        + output_tokens * rates.get("output", 0.0)
    ) / 1_000_000.0
    return cost, True
