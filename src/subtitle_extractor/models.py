from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class SubtitleSegment(BaseModel):
    id: int = Field(ge=0)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def end_must_follow_start(self) -> "SubtitleSegment":
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class SubtitleDocument(BaseModel):
    schema_version: str = "subtitle-document/v1"
    media_file: str
    source_language: str
    segments: list[SubtitleSegment]


class TranscriptionRequest(BaseModel):
    media_path: str
    language: str = "auto"

    def resolved_media_path(self) -> Path:
        return Path(self.media_path).expanduser().resolve()


class TranscriptionResponse(BaseModel):
    backend: str
    model: str
    document: SubtitleDocument

