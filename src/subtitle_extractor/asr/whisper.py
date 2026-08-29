from __future__ import annotations

import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

from subtitle_extractor.models import SubtitleDocument, SubtitleSegment


class WhisperAsrBackend:
    name = "whisper"

    def __init__(
        self,
        *,
        model_path: Path,
        device: str,
        dtype: str,
        attention: str,
        task: str,
        ffmpeg_path: str,
        chunk_seconds: int,
        temp_root: Path,
    ) -> None:
        self.model_path = model_path.expanduser().resolve()
        self.model_name = self.model_path.name
        self.device = device
        self.dtype_name = dtype
        self.attention = attention
        self.task = task
        self.ffmpeg_path = ffmpeg_path
        self.chunk_seconds = chunk_seconds
        self.temp_root = temp_root
        self._pipeline: Any | None = None

    def _load_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline

        try:
            import torch
            import transformers
            from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
        except ImportError as exc:
            raise RuntimeError(
                "Whisper dependencies are missing. Install the asr extra and a ROCm PyTorch build."
            ) from exc

        version_parts = tuple(int(part) for part in transformers.__version__.split(".")[:2])
        if version_parts < (4, 53):
            raise RuntimeError(
                f"Transformers {transformers.__version__} is too old; 4.53 or newer is required"
            )
        if not self.model_path.is_dir():
            raise FileNotFoundError(f"Whisper model directory not found: {self.model_path}")
        if self.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("ROCm/CUDA device is not available through torch.cuda")

        dtype = getattr(torch, self.dtype_name, None)
        if dtype is None:
            raise ValueError(f"Unsupported torch dtype: {self.dtype_name}")

        processor = AutoProcessor.from_pretrained(self.model_path, local_files_only=True)
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            self.model_path,
            dtype=dtype,
            low_cpu_mem_usage=True,
            use_safetensors=True,
            local_files_only=True,
            attn_implementation=self.attention,
        ).to(self.device)
        model.generation_config.forced_decoder_ids = None
        self._pipeline = pipeline(
            "automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            dtype=dtype,
            device=self.device,
        )
        return self._pipeline

    def transcribe(self, media_path: Path, language: str) -> SubtitleDocument:
        if shutil.which(self.ffmpeg_path) is None:
            raise RuntimeError(f"FFmpeg executable not found: {self.ffmpeg_path}")

        self.temp_root.mkdir(parents=True, exist_ok=True)
        pipeline = self._load_pipeline()
        segments: list[SubtitleSegment] = []
        offset = 0.0

        with tempfile.TemporaryDirectory(prefix="whisper-", dir=self.temp_root) as temp_dir:
            chunk_pattern = Path(temp_dir) / "chunk-%06d.wav"
            self._extract_audio_chunks(media_path, chunk_pattern)
            chunk_paths = sorted(Path(temp_dir).glob("chunk-*.wav"))
            if not chunk_paths:
                raise RuntimeError(f"FFmpeg produced no audio chunks for: {media_path}")

            for chunk_path in chunk_paths:
                duration = self._wav_duration(chunk_path)
                result = pipeline(
                    str(chunk_path),
                    return_timestamps=True,
                    generate_kwargs=self._generate_kwargs(language),
                )
                segments.extend(self._segments_from_result(result, offset, duration, len(segments)))
                offset += duration

        source_language = "und" if language == "auto" else language
        return SubtitleDocument(
            media_file=str(media_path),
            source_language=source_language,
            segments=segments,
        )

    def _extract_audio_chunks(self, media_path: Path, output_pattern: Path) -> None:
        command = [
            self.ffmpeg_path,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(media_path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            "-f",
            "segment",
            "-segment_time",
            str(self.chunk_seconds),
            "-reset_timestamps",
            "1",
            str(output_pattern),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            detail = completed.stderr.strip()[-1000:]
            raise RuntimeError(f"FFmpeg audio extraction failed: {detail}")

    def _generate_kwargs(self, language: str) -> dict[str, str]:
        kwargs = {"task": self.task}
        if language != "auto":
            kwargs["language"] = language
        return kwargs

    @staticmethod
    def _wav_duration(path: Path) -> float:
        with wave.open(str(path), "rb") as audio:
            return audio.getnframes() / audio.getframerate()

    @staticmethod
    def _segments_from_result(
        result: dict[str, Any],
        offset: float,
        chunk_duration: float,
        first_id: int,
    ) -> list[SubtitleSegment]:
        raw_chunks = result.get("chunks")
        if not isinstance(raw_chunks, list):
            raw_chunks = []
        if not raw_chunks and str(result.get("text", "")).strip():
            raw_chunks = [{"text": result["text"], "timestamp": (0.0, chunk_duration)}]

        segments: list[SubtitleSegment] = []
        for raw_chunk in raw_chunks:
            if not isinstance(raw_chunk, dict):
                raise TypeError("Whisper returned a malformed subtitle chunk")
            text = str(raw_chunk.get("text", "")).strip()
            timestamp = raw_chunk.get("timestamp")
            if not text:
                continue
            if not isinstance(timestamp, (tuple, list)) or len(timestamp) != 2:
                raise RuntimeError(f"Whisper returned a malformed timestamp: {timestamp!r}")
            start, end = timestamp
            if not isinstance(start, (int, float)):
                raise TypeError(f"Whisper returned an invalid start timestamp: {timestamp!r}")
            if end is None:
                end = chunk_duration
            if not isinstance(end, (int, float)) or end <= start:
                raise RuntimeError(f"Whisper returned an invalid timestamp range: {timestamp!r}")
            segments.append(
                SubtitleSegment(
                    id=first_id + len(segments),
                    start=round(offset + float(start), 3),
                    end=round(offset + float(end), 3),
                    text=text,
                )
            )
        return segments
