# container/web.Dockerfile — the console's own image, separate from the
# tenant image (container/Dockerfile). Companion ticket: testbed owns the
# compose service / setup.sh wiring that runs this against a tenant; this
# file only builds it.
#
# ⚠ NOT the tenant image, and not a change to
# SPEC-bundled-clients-and-exposure.md's "operator starts it deliberately"
# stance — clients/web is still not bundled into or auto-started by any
# tenant's entrypoint.sh. This packages it as its own image so it can run as
# its own container on a tenant's docker network instead of a bare `python3
# server.py` on someone's host, nothing more.
#
# clients/web/server.py is stdlib-only (check its own imports before adding
# a dependency here) — no pip install, no venv, nothing to build.
FROM python:3.12-slim

RUN useradd --create-home --uid 1000 console

WORKDIR /app
COPY clients/web/ ./clients/web/
RUN chown -R console:console /app

USER console

# ⚠ Binds every interface *inside this container* — the same rule
# container/Dockerfile's API_BIND/SESSION_BIND documents for the tenant's own
# doors. Publishing (or, here, routing from a reverse proxy on the shared
# docker network) is a decision made elsewhere, never this image's. Because
# this is non-loopback by design, server.py's own non-loopback-without-a-
# secret guard applies: HFLOCK_SECRET is REQUIRED for this container to start
# at all, the same way API_TOKEN is required and default-free for the tenant
# image (container/compose.yaml). WEB_PORT is deliberately NOT redeclared
# here — server.py's own --port/WEB_PORT default (8090) applies unless the
# caller sets it, so there is exactly one place that default lives.
ENV WEB_LISTEN=0.0.0.0 \
    PYTHONUNBUFFERED=1

EXPOSE 8090

ENTRYPOINT ["python3", "clients/web/server.py"]
