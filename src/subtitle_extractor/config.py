from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SUBTITLE_EXTRACTOR_",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8011
    backend: str = "whisper"
    model: str = "/home/simon/models/whisper-large-v3"
    device: str = "cuda:0"
    dtype: str = "float16"
    attention: str = "sdpa"
    language: str = "english"
    task: str = "transcribe"

    input_dir: Path = Path("/home/simon/modeling-video")
    data_dir: Path = Path("/home/simon/subtitle-output")
    media_extensions: str = ".mp4,.mkv,.mov,.webm,.m4v,.avi"
    file_settle_seconds: int = Field(default=60, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    stale_lock_seconds: int = Field(default=3600, ge=1)
    profile_version: int = Field(default=1, ge=1)

    ffmpeg_path: str = "ffmpeg"
    ffmpeg_chunk_seconds: int = Field(default=600, ge=30, le=3600)

    @property
    def allowed_extensions(self) -> frozenset[str]:
        return frozenset(
            extension if extension.startswith(".") else f".{extension}"
            for item in self.media_extensions.split(",")
            if (extension := item.strip().lower())
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
