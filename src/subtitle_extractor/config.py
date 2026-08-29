from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SUBTITLE_EXTRACTOR_",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8011
    backend: str = "mock"
    model: str = "openai/whisper-large-v3-turbo"
    device: str = "cuda"


@lru_cache
def get_settings() -> Settings:
    return Settings()

