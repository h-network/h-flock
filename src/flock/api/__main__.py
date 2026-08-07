"""Run the flock API with uvicorn."""

import uvicorn

from .app import Settings, create_app


def main() -> None:
    settings = Settings.from_env()
    settings.validate()
    uvicorn.run(create_app(settings=settings), host=settings.api_bind, port=settings.api_port)


if __name__ == "__main__":
    main()
