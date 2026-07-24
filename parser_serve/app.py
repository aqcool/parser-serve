"""ASGI entrypoint for Parser Serve."""

from .api import create_app
from .persistence import Database
from .observability import configure_logging
from .settings import LogFormat, get_settings


settings = get_settings()
configure_logging(
    level=settings.log_level,
    json_output=settings.log_format is LogFormat.JSON,
)
app = create_app(
    settings,
    database=Database(settings.database_url, echo=settings.database_echo),
    dispose_database_on_shutdown=True,
)

__all__ = ["app", "create_app"]
