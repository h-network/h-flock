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
