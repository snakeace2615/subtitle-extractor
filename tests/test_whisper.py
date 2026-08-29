import pytest

from subtitle_extractor.asr.whisper import WhisperAsrBackend


def test_segments_apply_global_chunk_offset() -> None:
    segments = WhisperAsrBackend._segments_from_result(
        {
            "chunks": [
                {"timestamp": (1.25, 3.5), "text": " Hello "},
                {"timestamp": (4.0, None), "text": "world"},
            ]
        },
        offset=600.0,
        chunk_duration=10.0,
        first_id=3,
    )

    assert [(item.id, item.start, item.end, item.text) for item in segments] == [
        (3, 601.25, 603.5, "Hello"),
        (4, 604.0, 610.0, "world"),
    ]


def test_segments_reject_timestamp_reset_within_document() -> None:
    with pytest.raises(ValueError, match="ordered"):
        from subtitle_extractor.models import SubtitleDocument, SubtitleSegment

        SubtitleDocument(
            media_file="demo.mp4",
            source_language="english",
            segments=[
                SubtitleSegment(id=0, start=2, end=3, text="later"),
                SubtitleSegment(id=1, start=1, end=2, text="earlier"),
            ],
        )
