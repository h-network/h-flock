# Pin the base because it owns the untested startAgent and CLI launch contract.
# Update the digest only after rebuilding and running acceptance.
FROM ghcr.io/h-network/base@sha256:10406097c8954af16c62cf0088dea147065146bf4f667c361da96384ed02cbdc

USER root

# tini reaps children abandoned by agent CLIs; Redis is the tenant-local bus.
RUN apt-get update \
 && apt-get install -y --no-install-recommends redis-server tini procps \
 && rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 marks the system interpreter externally managed (PEP 668).
ENV VIRTUAL_ENV=/opt/flock
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN python3 -m venv "$VIRTUAL_ENV"

WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
COPY clients/ ./clients/
RUN pip install --no-cache-dir .

# The base seeds Claude and Codex. It does not seed agy, so this image must.
COPY container/config/pricing.json         /app/container/config/pricing.json
RUN mkdir -p /etc/flock \
 && cp /app/container/config/pricing.json /etc/flock/pricing.json \
 && chown -R ubuntu:ubuntu /home/ubuntu/.claude /home/ubuntu/.codex /app/container /app/clients /etc/flock

COPY container/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY container/supervise-service.sh /usr/local/bin/supervise-service.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/supervise-service.sh

# This marker suppresses agy's headless first-run gates. Workspace-specific
# trust and telemetry settings are written later by flock.tmux.ops.
RUN mkdir -p /home/ubuntu/.gemini/antigravity-cli/cache \
 && python3 -c "import json, os; p='/home/ubuntu/.gemini/antigravity-cli/cache/onboarding.json'; d=json.load(open(p)) if os.path.exists(p) else {}; d.update({'consumerOnboardingComplete': True, 'enterpriseOnboardingComplete': False, 'onboardingComplete': True}); json.dump(d, open(p,'w'), indent=2)" \
 && chown -R ubuntu:ubuntu /home/ubuntu/.gemini

# The unprivileged runtime user must own the tmux socket and agent worktree roots.
RUN mkdir -p /home/ubuntu/.flock/tmux /workdir \
 && chown -R ubuntu:ubuntu /home/ubuntu/.flock /opt/flock /workdir

# Do not set REDIS_URL image-wide: the tmux server would expose it to every agent.
# Keep these tuning defaults aligned with their code defaults.
ENV PYTHONUNBUFFERED=1 \
    ROSTER_POLL_SECONDS=5 \
    ACTIVITY_POLL_SECONDS=2 \
    PRESENCE_WORKING_SECONDS=30 \
    DONE_TASK_MAX=500 \
    DEAD_LETTER_MAX=500 \
    WINDOW_LOG_MAX_BYTES=8388608 \
    TMUX_TMPDIR=/home/ubuntu/.flock/tmux \
    API_LISTEN_PORT=8080 \
    TERMINAL_LISTEN_PORT=8081

# Publication is separate from these container-internal listen addresses.
ENV API_LISTEN_ADDRESS=0.0.0.0 \
    TERMINAL_LISTEN_ADDRESS=0.0.0.0

USER ubuntu

ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/entrypoint.sh"]
