# One container is one tenant — LLD-container §1.
FROM python:3.12-slim

# tini is PID 1 so the children agent CLIs spawn and abandon are reaped rather
# than accumulating as zombies (LLD-container §6). redis and tmux are the
# tenant's own, never shared and never published.
RUN apt-get update \
 && apt-get install -y --no-install-recommends redis-server tmux tini procps curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY container/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    REDIS_URL=redis://127.0.0.1:6379/0 \
    ROSTER_POLL_SECONDS=5 \
    TMUX_TMPDIR=/run/flock-tmux \
    API_PORT=8080

# The api binds every interface *inside* the container; publishing is the
# deliberate act, and compose maps it to the host's loopback only. A
# non-loopback bind with no token refuses to start (LLD-api §6), which is what
# makes the token mandatory here rather than advisory (LLD-container §3).
ENV API_BIND=0.0.0.0

ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/entrypoint.sh"]
