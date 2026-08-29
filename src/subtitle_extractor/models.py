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
    media_file: str = Field(min_length=1)
    source_language: str = Field(min_length=1)
    segments: list[SubtitleSegment]

    @model_validator(mode="after")
    def segments_must_be_unique_and_ordered(self) -> "SubtitleDocument":
        seen_ids: set[int] = set()
        previous_start = -1.0
        for segment in self.segments:
            if segment.id in seen_ids:
                raise ValueError(f"duplicate segment id: {segment.id}")
            if segment.start < previous_start:
                raise ValueError("segments must be ordered by start time")
            seen_ids.add(segment.id)
            previous_start = segment.start
        return self


class TranscriptionRequest(BaseModel):
    media_path: str
    language: str = "auto"

    def resolved_media_path(self) -> Path:
        return Path(self.media_path).expanduser().resolve()


class TranscriptionResponse(BaseModel):
    backend: str
    model: str
    document: SubtitleDocument
