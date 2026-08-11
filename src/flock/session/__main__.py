"""Run the flock session WebSocket service."""

import uvicorn

from .app import SessionSettings, create_app


def main() -> None:
    settings = SessionSettings.from_env()
    settings.validate()
    kwargs = {}
    if settings.session_tls_cert and settings.session_tls_key:
        kwargs["ssl_certfile"] = settings.session_tls_cert
        kwargs["ssl_keyfile"] = settings.session_tls_key
    uvicorn.run(
        create_app(settings=settings),
        host=settings.session_bind,
        port=settings.session_port,
        access_log=False,
        **kwargs,
    )


if __name__ == "__main__":
    main()
