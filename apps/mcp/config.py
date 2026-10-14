"""Runtime configuration for the MCP server and answer worker."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    temporal_address: str = "localhost:7233"
    elasticsearch_url: str = "http://localhost:9200"
    kilt_index: str = "kilt"
