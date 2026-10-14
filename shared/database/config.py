"""Database configuration shared by entry points and migrations."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    db_host: str = "localhost"
    db_port: str = "5432"
    db_name: str = "my_db"
    db_user: str = "postgres"
    db_password: str = "postgres"
    test_database_url: str = "sqlite+aiosqlite:///:memory:"

    @property
    def database_url(self) -> str:
        """Build the PostgreSQL DSN from the database settings."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )
