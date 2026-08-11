import os
from pathlib import Path
from unittest.mock import patch

from flock.tmuxhost import __main__ as tmuxhost_main


def test_tmuxhost_consumes_redis_url_before_starting_host():
    seen = {}

    class FakeHost:
        def __init__(self, **kwargs):
            seen["redis_url"] = kwargs["redis_url"]

        def run_forever(self):
            seen["inherited"] = os.environ.get("REDIS_URL")

    with patch.dict(os.environ, {"REDIS_URL": "redis://:secret@127.0.0.1:6379/0"}, clear=False):
        with patch.object(tmuxhost_main, "TmuxHost", FakeHost):
            tmuxhost_main.main()

    assert seen == {"redis_url": "redis://:secret@127.0.0.1:6379/0", "inherited": None}


def test_entrypoint_drops_redis_credentials_before_tmuxhost():
    script = Path("container/entrypoint.sh").read_text()
    unset_at = script.index("unset REDIS_PASSWORD REDISCLI_AUTH REDIS_URL")
    tmuxhost_at = script.index("start tmuxhost")

    assert unset_at < tmuxhost_at
    assert 'start tmuxhost env REDIS_URL="$redis_url"' in script
