import os
import sys
from flock.tmuxhost.host import TmuxHost


def main() -> None:
    pod = os.environ.get("POD", "default")
    tenant = os.environ.get("TENANT", "default")
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    poll_seconds = float(os.environ.get("ROSTER_POLL_SECONDS", "5"))
    session_name = os.environ.get("TMUX_SESSION", tenant)
    socket = os.environ.get("TMUX_SOCKET")

    host = TmuxHost(
        pod=pod,
        tenant=tenant,
        redis_url=redis_url,
        poll_seconds=poll_seconds,
        session_name=session_name,
        socket=socket,
    )
    host.run_forever()


if __name__ == "__main__":
    main()
