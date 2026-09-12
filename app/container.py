"""Compose entry point; adapt the host URL without changing the user's .env."""

from pydantic import SecretStr
from sqlalchemy.engine import make_url

from app.config import Settings


def container_settings(settings: Settings) -> Settings:
    """Preserve credentials while selecting Compose's internal database address."""
    if not settings.database_url.get_secret_value():
        raise RuntimeError("DATABASE_URL is required for container startup.")
    url = make_url(settings.database_url.get_secret_value()).set(host="db", port=5432)
    return settings.model_copy(
        update={"database_url": SecretStr(url.render_as_string(hide_password=False))}
    )


def main() -> None:
    import uvicorn

    from app.main import create_app

    uvicorn.run(
        create_app(container_settings(Settings())), host="0.0.0.0", port=8000, access_log=False
    )


if __name__ == "__main__":
    main()
