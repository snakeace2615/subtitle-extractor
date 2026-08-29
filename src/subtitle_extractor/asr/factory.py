from pathlib import Path

from subtitle_extractor.asr.base import AsrBackend
from subtitle_extractor.asr.mock import MockAsrBackend
from subtitle_extractor.asr.whisper import WhisperAsrBackend
from subtitle_extractor.config import Settings


def create_backend(settings: Settings) -> AsrBackend:
    if settings.backend == "mock":
        return MockAsrBackend()
    if settings.backend == "whisper":
        return WhisperAsrBackend(
            model_path=Path(settings.model),
            device=settings.device,
            dtype=settings.dtype,
            attention=settings.attention,
            task=settings.task,
            ffmpeg_path=settings.ffmpeg_path,
            chunk_seconds=settings.ffmpeg_chunk_seconds,
            temp_root=settings.data_dir.expanduser() / "temp",
        )
    raise RuntimeError(f"Unsupported ASR backend: {settings.backend}")
