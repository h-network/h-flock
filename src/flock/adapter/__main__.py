import os
import sys
from flock.adapter.runner import run_adapter


def main() -> None:
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: flock.adapter <agent>\n")
        sys.exit(1)

    agent = sys.argv[1]
    pod = os.environ.get("POD", "default")
    tenant = os.environ.get("TENANT", "default")
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    session_name = os.environ.get("TMUX_SESSION", tenant)
    socket = os.environ.get("TMUX_SOCKET")

    run_adapter(
        agent=agent,
        pod=pod,
        tenant=tenant,
        redis_url=redis_url,
        session_name=session_name,
        socket=socket,
    )


if __name__ == "__main__":
    main()
