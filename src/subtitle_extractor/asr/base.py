from pathlib import Path
from typing import Protocol

from subtitle_extractor.models import SubtitleDocument


class AsrBackend(Protocol):
    name: str
    model_name: str

    def transcribe(self, media_path: Path, language: str) -> SubtitleDocument: ...

