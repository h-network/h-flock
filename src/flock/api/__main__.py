"""Run the flock API with uvicorn."""

import uvicorn

from .app import Settings, create_app


def main() -> None:
    settings = Settings.from_env()
    settings.validate()
    kwargs = {}
    if settings.api_tls_cert and settings.api_tls_key:
        kwargs["ssl_certfile"] = settings.api_tls_cert
        kwargs["ssl_keyfile"] = settings.api_tls_key
    uvicorn.run(create_app(settings=settings), host=settings.api_bind, port=settings.api_port, **kwargs)


if __name__ == "__main__":
    main()
