"""Configured account discovery shared by the office client and fabric."""

import os
from pathlib import Path

from .keys import SEGMENT_REGEX


def available_profiles(home_root: Path | None = None) -> tuple[str, ...]:
    """Return account config directories that actually exist in this tenant."""
    root = home_root or Path(os.environ.get("HOME", "/home/ubuntu"))
    profiles = {"default"}
    for cli_dir in (".claude-", ".codex-"):
        for path in root.glob(f"{cli_dir}*"):
            if path.is_dir() and SEGMENT_REGEX.fullmatch(path.name[len(cli_dir):]):
                profiles.add(path.name[len(cli_dir):])
    return tuple(sorted(profiles))
