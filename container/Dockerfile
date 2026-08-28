# One container is one tenant — LLD-container §1.
#
# The h-network base carries tmux and the agent CLIs (claude, codex, agy) plus
# startAgent, so a window can run a real agent rather than a mock shell. It does
# not carry redis or an init, which are this container's own concerns.
# ⚠ PINNED BY DIGEST, NOT `:latest`. The base owns `startAgent` and the agent
# CLIs, so it decides how every window launches — and nothing in this repository
# executes `startAgent` or asserts it works. The two tests that mention it check
# that we CONSTRUCT the string; `run_tmux` is mocked. All 432 tests stay green if
# the base drops it entirely.
#
# ⚠ So an unpinned base change lands on the next `--build` and shows up as silent
# agents — the same signature as a login prompt, a first-run dialog or a wedged
# CLI. Pinned, absorbing a base change is a commit here that can be reverted.
#
# This is also what makes it safe to iterate on the base from a tenant that is
# itself running on it: the office keeps this digest while the new one is built.
#
# To update: `docker buildx imagetools inspect ghcr.io/h-network/base:latest`,
# take `Digest:`, change the line below, rebuild, and run acceptance. Record the
# digest in the build's results (`BUILD-CONVENTION` §3.0).
FROM ghcr.io/h-network/base@sha256:10406097c8954af16c62cf0088dea147065146bf4f667c361da96384ed02cbdc

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
COPY clients/ ./clients/
RUN pip install --no-cache-dir .

# ⚠ CLI defaults and first-run gates for claude and codex come from the BASE
# IMAGE now, not from here. They lived in this file until 2026-08-23 as a copy
# of h-office's; base owns them because they describe how to run an agent CLI
# unattended, which is not h-flock's business. Deleting the copy rather than
# merging it is deliberate: this image builds on that base and only that base,
# so a second copy would be drift rather than a fallback.
#
# ⚠ agy is STILL OURS, below. Base suppresses claude's and codex's dialogs and
# refuses agy outright (`seedProfile agy` exits 3), so its three gates are
# h-flock's to answer for as long as we hire agy agents.
COPY container/config/pricing.json         /app/container/config/pricing.json
RUN mkdir -p /etc/flock \
 && cp /app/container/config/pricing.json /etc/flock/pricing.json \
 && chown -R ubuntu:ubuntu /home/ubuntu/.claude /home/ubuntu/.codex /app/container /app/clients /etc/flock

COPY container/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY container/supervise-service.sh /usr/local/bin/supervise-service.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/supervise-service.sh

# agy shows three first-run gates — a colour-scheme picker, a pre-checked
# consent to send interaction data to Google, and a workspace-trust prompt — and
# a headless agent stops dead on the first. All three are suppressed by ONE
# marker, written when onboarding completes:
#
# ⚠ Found by clearing the prompts by hand in a live tenant and diffing the disk.
# jetski_state.pbtxt's post_onboarding block looks like the right place and is
# not: seeding it changed nothing, and completing onboarding wrote only this
# file. Do not "restore" the pbtxt seeding.
#
# Image-level because it carries no path. The per-directory half — trust, and
# enableTelemetry=false — is written per agent by flock.tmux.ops at window
# creation, since trustedWorkspaces needs the agent's own directory.
RUN mkdir -p /home/ubuntu/.gemini/antigravity-cli/cache \
 && python3 -c "import json, os; p='/home/ubuntu/.gemini/antigravity-cli/cache/onboarding.json'; d=json.load(open(p)) if os.path.exists(p) else {}; d.update({'consumerOnboardingComplete': True, 'enterpriseOnboardingComplete': False, 'onboardingComplete': True}); json.dump(d, open(p,'w'), indent=2)" \
 && chown -R ubuntu:ubuntu /home/ubuntu/.gemini

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
# ⚠ A TUNING DEFAULT SET HERE SILENTLY BEATS THE ONE IN THE CODE, because the
# code reads `os.environ.get(NAME, default)` and this makes NAME always present.
# `VERIFY_AFTER_SECONDS=10` used to live in this block. Build 81 raised the class
# default to 120 and build 80 raised `service.py`'s fallback to 120 — and the
# window in a running tenant stayed 10, because this line won both times. Two
# lanes fixed it, neither fix reached production. It is gone; `service.py` owns
# it now, and an operator can still set it in the tenant's generated `.env`.
#
# ⚠ The two below duplicate their code defaults and currently AGREE, which is the
# only reason they are not the same bug. Change one and you must change both —
# or better, delete it here as `VERIFY_AFTER_SECONDS` was deleted.
ENV PYTHONUNBUFFERED=1 \
    ROSTER_POLL_SECONDS=5 \
    ACTIVITY_POLL_SECONDS=2 \
    PRESENCE_WORKING_SECONDS=30 \
    BOARD_DONE_MAX=500 \
    DEAD_MAX=500 \
    WINDOW_LOG_MAX_BYTES=8388608 \
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
