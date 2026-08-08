"""Run the flock session WebSocket service."""

import uvicorn

from .app import SessionSettings, create_app


def main() -> None:
    settings = SessionSettings.from_env()
    uvicorn.run(
        create_app(settings=settings),
        host=settings.session_bind,
        port=settings.session_port,
    )


if __name__ == "__main__":
    main()
