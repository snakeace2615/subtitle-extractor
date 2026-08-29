from pathlib import Path

from subtitle_extractor.models import SubtitleDocument, SubtitleSegment


class MockAsrBackend:
    name = "mock"
    model_name = "mock-asr"

    def transcribe(self, media_path: Path, language: str) -> SubtitleDocument:
        source_language = "und" if language == "auto" else language
        return SubtitleDocument(
            media_file=str(media_path),
            source_language=source_language,
            segments=[
                SubtitleSegment(
                    id=0,
                    start=0.0,
                    end=2.0,
                    text="Mock subtitle: ASR backend is not configured yet.",
                )
            ],
        )
