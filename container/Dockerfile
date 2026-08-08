# One container is one tenant — LLD-container §1.
#
# The h-network base carries tmux and the agent CLIs (claude, codex, agy) plus
# startAgent, so a window can run a real agent rather than a mock shell. It does
# not carry redis or an init, which are this container's own concerns.
FROM ghcr.io/h-network/base:latest

USER root

# tini is PID 1 so the children agent CLIs spawn and abandon are reaped rather
# than accumulating as zombies (LLD-container §6). That matters more with real
# CLIs in the windows than it did with bash. redis is the tenant's own bus,
# never shared and never published.
RUN apt-get update \
 && apt-get install -y --no-install-recommends redis-server tini procps \
 && rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 marks the system interpreter externally-managed (PEP 668), so
# flock gets its own venv rather than fighting it. Putting the venv's bin on
# PATH is what makes `send` and `flock.adapter` available to every agent window
# and to the router's kick.
ENV VIRTUAL_ENV=/opt/flock
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN python3 -m venv "$VIRTUAL_ENV"

WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY container/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Claude Code keeps first-run state in ~/.claude.json. Without hasCompletedOnboarding
# an agent's first `startAgent` lands on the theme picker instead of a prompt —
# which for an agent in a headless window means it never starts at all. The base
# image does not set it; h-office pre-seeds the same flag for the same reason.
# Merged into the existing file rather than overwritten: it carries installMethod,
# machineID and migration flags that should survive.
RUN python3 -c "import json, os; p='/home/ubuntu/.claude.json'; d=json.load(open(p)) if os.path.exists(p) else {}; d['hasCompletedOnboarding']=True; json.dump(d, open(p,'w'), indent=2)" \
 && chown ubuntu:ubuntu /home/ubuntu/.claude.json

# The base runs as ubuntu (uid 1000), and the agent CLIs expect that home. The
# tmux socket therefore lives somewhere that user owns — /run is root's.
# /workdir is where each agent gets its own home (LLD-tmux-host §5). The host
# creates /workdir/<agent> as the `ubuntu` user, so the parent has to exist and
# be writable by it — otherwise makedirs fails silently and the window falls
# back to /app, which is h-flock's own source.
RUN mkdir -p /home/ubuntu/.flock/tmux /workdir \
 && chown -R ubuntu:ubuntu /home/ubuntu/.flock /opt/flock /workdir

# REDIS_URL is deliberately NOT set image-wide. Every module defaults it to
# redis://127.0.0.1:6379/0, which is a fact rather than configuration inside a
# tenant (LLD-container §1). Setting it here put it in the tmux server's
# environment and therefore in every agent's, which is how an agent asked "where
# are my peers" found a database instead. The entrypoint hands it to the router,
# which is the only module that requires it.
ENV PYTHONUNBUFFERED=1 \
    ROSTER_POLL_SECONDS=5 \
    TMUX_TMPDIR=/home/ubuntu/.flock/tmux \
    API_PORT=8080 \
    SESSION_PORT=8081

# The api binds every interface *inside* the container; publishing is the
# deliberate act, and compose maps it to the host's loopback only. A
# non-loopback bind with no token refuses to start (LLD-api §6), which is what
# makes the token mandatory here rather than advisory (LLD-container §3).
ENV API_BIND=0.0.0.0 \
    SESSION_BIND=0.0.0.0

USER ubuntu

ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/entrypoint.sh"]
