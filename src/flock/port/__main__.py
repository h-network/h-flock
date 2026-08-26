import os
import signal
import sys
from flock.port.deliver import run_port


def main() -> None:
    # The switch ignores SIGCHLD so its fire-and-forget port children are
    # reaped by the kernel.  An ignored disposition survives exec, but a port
    # must wait for its own tmux clients and observe their real exit statuses.
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)

    if len(sys.argv) < 2:
        sys.stderr.write("Usage: flock.port <agent>\n")
        sys.exit(1)

    agent = sys.argv[1]
    pod = os.environ.get("POD", "default")
    tenant = os.environ.get("TENANT", "default")
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    session_name = os.environ.get("TMUX_SESSION", tenant)
    socket = os.environ.get("TMUX_SOCKET")

    run_port(
        agent=agent,
        pod=pod,
        tenant=tenant,
        redis_url=redis_url,
        session_name=session_name,
        socket=socket,
    )


if __name__ == "__main__":
    main()
