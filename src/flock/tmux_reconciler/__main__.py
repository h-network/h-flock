import os
import sys
from flock.tmux_reconciler.service import TmuxReconciler


def main() -> None:
    pod = os.environ.get("POD", "default")
    tenant = os.environ.get("TENANT", "default")
    # tmux_reconciler needs the credential, but the tmux server it creates must not
    # inherit it and pass it to every agent window. Consume it before the first
    # tmux command rather than merely reading it from the environment.
    redis_url = os.environ.pop("REDIS_URL", "redis://127.0.0.1:6379/0")
    poll_seconds = float(os.environ.get("ROSTER_POLL_SECONDS", "5"))
    session_name = os.environ.get("TMUX_SESSION", tenant)
    socket = os.environ.get("TMUX_SOCKET")

    reconciler = TmuxReconciler(
        pod=pod,
        tenant=tenant,
        redis_url=redis_url,
        poll_seconds=poll_seconds,
        session_name=session_name,
        socket=socket,
    )
    reconciler.run_forever()


if __name__ == "__main__":
    main()
