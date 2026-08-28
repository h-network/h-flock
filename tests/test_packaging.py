"""Dependencies whose absence is invisible to every other test.

Raised by an agent during the first live discussion run: `flock.session`'s
WebSocket route answers 404 without a WebSocket implementation, uvicorn ships
none, and FastAPI's TestClient does not need one — so the whole suite passes
with the dependency removed. It did: 62 passed with `websockets` uninstalled,
which is exactly the deploy that failed on the lab host.
"""


def test_a_websocket_implementation_is_installed():
    # Declared in pyproject. Without it flock.session's route 404s and uvicorn
    # only logs a warning, which reads as a wrong path rather than a missing
    # package.
    import websockets  # noqa: F401


def test_uvicorn_can_actually_serve_websockets():
    # The stronger check: uvicorn resolves its WebSocket protocol at import
    # time and leaves it None when no implementation is available. Asserting on
    # uvicorn's own resolution catches the case where a library is installed but
    # uvicorn cannot use it.
    from uvicorn.protocols.websockets.auto import AutoWebSocketsProtocol

    assert AutoWebSocketsProtocol is not None, (
        "uvicorn has no usable WebSocket implementation — flock.session will "
        "answer 404 on /session and only log a warning"
    )


def test_image_env_does_not_shadow_a_diverging_code_default():
    """⚠ An image ENV silently beats the code default it duplicates.

    `VERIFY_AFTER_SECONDS=10` lived in the Dockerfile ENV block. Build 81 raised
    the class default to 120 and build 80 raised `service.py`'s fallback to 120,
    and a running tenant still used 10 — measured on h-oracle 2026-08-22, where
    the watchdog's `/proc/<pid>/environ` read `VERIFY_AFTER_SECONDS=10` while the
    installed source read `"120"`. Two lanes fixed it; neither fix reached
    production.

    This fails when the image sets a tuning knob to a value the code disagrees
    with, which is the only case that is silently wrong.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    dockerfile = (root / "container" / "Dockerfile").read_text()

    image = {}
    for match in re.finditer(r"^\s*(?:ENV\s+)?([A-Z][A-Z0-9_]+)=(\S+)", dockerfile, re.M):
        image[match.group(1)] = match.group(2).rstrip("\\").strip()

    mismatched = []
    for path in (root / "src").rglob("*.py"):
        text = path.read_text()
        for name, default in re.findall(
            r'environ\.get\(\s*"([A-Z][A-Z0-9_]+)"\s*,\s*"([^"]*)"\s*\)', text
        ):
            if name in image and image[name] != default:
                mismatched.append(
                    f"{name}: image={image[name]!r} code={default!r} ({path.name})"
                )

    assert not mismatched, (
        "the image ENV overrides a different code default, so the code default "
        f"is dead: {mismatched}"
    )


def test_every_container_record_carries_a_writer():
    """⚠ The container's own records are shell echoes and bypass log_record.

    Build 80 gave every Python-emitted record a `writer`. The 7 lifecycle records
    the entrypoint emits are `printf`/`print` of literal JSON and reached the
    custody log with no writer at all — 44 of 300 records in the build 81 live
    run, found in that run's writer census, not by a test.
    """
    import pathlib
    import re

    entrypoint = (
        pathlib.Path(__file__).resolve().parents[1] / "container" / "entrypoint.sh"
    ).read_text()

    missing = []
    for match in re.finditer(r'\{\\?"module\\?":\\?"container\\?"(.{0,120})', entrypoint):
        if "writer" not in match.group(1):
            line = entrypoint[: match.start()].count("\n") + 1
            missing.append(f"entrypoint.sh:{line}")

    assert not missing, f"container records with no writer: {missing}"


def test_pricing_config_is_copied_into_container_image():
    """⚠ container/config/pricing.json must be present in the built container image.

    Otherwise load_pricing falls back to hardcoded defaults and editing the
    configuration file has no effect.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    assert (root / "container" / "config" / "pricing.json").is_file(), "pricing.json missing from repository"

    dockerfile = (root / "container" / "Dockerfile").read_text()
    assert "container/config/pricing.json" in dockerfile, (
        "pricing.json is not COPYed in container/Dockerfile; container will fall back to hardcoded defaults"
    )


def test_web_dockerfile_copies_the_console_and_binds_every_interface():
    """container/web.Dockerfile is clients/web/server.py's own image, separate
    from the tenant image — its contract with testbed's companion compose/
    setup.sh ticket is WEB_LISTEN=0.0.0.0 (routable from a reverse proxy on
    the shared docker network) and WEB_PORT left undeclared so server.py's
    own --port/WEB_PORT default (8090) stays the only place that default
    lives — see test_image_env_does_not_shadow_a_diverging_code_default for
    why a duplicated default is the trap this avoids.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    dockerfile_path = root / "container" / "web.Dockerfile"
    assert dockerfile_path.is_file(), "container/web.Dockerfile is missing"
    dockerfile = dockerfile_path.read_text()

    assert "COPY clients/web/" in dockerfile, "web.Dockerfile does not copy clients/web/ into the image"

    image_env = {
        match.group(1): match.group(2).rstrip("\\").strip()
        for match in re.finditer(r"^\s*(?:ENV\s+)?([A-Z][A-Z0-9_]+)=(\S+)", dockerfile, re.M)
    }
    assert image_env.get("WEB_LISTEN") == "0.0.0.0", (
        "web.Dockerfile must bind every interface inside its own container, "
        "same rule container/Dockerfile documents for API_BIND/SESSION_BIND"
    )
    assert "WEB_PORT" not in image_env, (
        "web.Dockerfile must not redeclare WEB_PORT — server.py's own default "
        "is the only place that value should live (see the diverging-default test above)"
    )
    assert "clients/web/server.py" in dockerfile, "web.Dockerfile's ENTRYPOINT must invoke clients/web/server.py"
