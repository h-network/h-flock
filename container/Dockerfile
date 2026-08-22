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

# ⚠ CLI defaults, baked. Ported from h-office, which had them and h-flock never
# did — h-flock only ever wrote enough to clear a trust prompt.
#
# Two of these are load-bearing rather than cosmetic:
#
#   attribution.commit/pr = ""   enforces AGENTS.md's "never add attribution
#     trailers" MECHANICALLY. Relying on the instruction alone means every agent
#     has to remember, every commit, forever.
#
#   promptSuggestionEnabled / awaySummaryEnabled / feedback surveys = off.
#     These make a pane look busy when it is not, which feeds presence and
#     produces delivery_unverified for an agent that is doing nothing wrong.
#
# codex's approval_policy/sandbox_mode duplicate what startAgent passes on the
# command line, deliberately: a bare `codex` run by an agent that forgot the
# wrapper otherwise stalls its window waiting for an approval nobody will give.
COPY container/config/claude/settings.json /home/ubuntu/.claude/settings.json
COPY container/config/codex/config.toml    /home/ubuntu/.codex/config.toml
COPY container/config/pricing.json         /app/container/config/pricing.json
RUN mkdir -p /etc/flock \
 && cp /app/container/config/pricing.json /etc/flock/pricing.json \
 && chown -R ubuntu:ubuntu /home/ubuntu/.claude /home/ubuntu/.codex /app/container /etc/flock

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

# The fourth first-run gate. startAgent passes --dangerously-skip-permissions,
# which has its own one-time "Bypass Permissions mode" acceptance dialog — and
# a headless agent stops dead on it. The base image ships no settings.json at
# all, so there is nothing suppressing it. Merged rather than written, so a
# settings.json arriving later via container/home keeps its own keys.
RUN mkdir -p /home/ubuntu/.claude \
 && python3 -c "import json, os; p='/home/ubuntu/.claude/settings.json'; d=json.load(open(p)) if os.path.exists(p) else {}; d['skipDangerousModePermissionPrompt']=True; json.dump(d, open(p,'w'), indent=2)" \
 && chown -R ubuntu:ubuntu /home/ubuntu/.claude

# Seed codex config.toml with check_for_update_on_startup = false.
# Suppresses the "Update available!" startup dialog whose default option runs
# `npm install -g @openai/codex` globally inside the container.
# Merged rather than overwritten so any existing config.toml keys survive.
# ⚠ Written FIRST, not appended. In TOML a bare key after a [section] header
# belongs to that section — appending it to a config.toml that carries
# [profiles.<name>] blocks (which container/home may deliver) would bury it
# inside the last one, where it parses cleanly and does nothing.
RUN mkdir -p /home/ubuntu/.codex \
 && python3 -c "import os; p='/home/ubuntu/.codex/config.toml'; old=open(p).read() if os.path.exists(p) else ''; keep=[l for l in old.splitlines() if not l.strip().startswith('check_for_update_on_startup')]; open(p,'w').write('\n'.join(['check_for_update_on_startup = false'] + keep) + '\n')" \
 && chown -R ubuntu:ubuntu /home/ubuntu/.codex

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
# it now, and an operator can still set it in `container/.env`.
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
