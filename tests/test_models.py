import pytest
from pydantic import ValidationError

from subtitle_extractor.models import SubtitleDocument, SubtitleSegment


def test_subtitle_document_contract() -> None:
    document = SubtitleDocument(
        media_file="demo.mp4",
        source_language="en",
        segments=[SubtitleSegment(id=0, start=0, end=1.5, text="Hello")],
    )
    assert document.schema_version == "subtitle-document/v1"


def test_segment_rejects_invalid_time_range() -> None:
    with pytest.raises(ValidationError):
        SubtitleSegment(id=0, start=2, end=1, text="Invalid")
