from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from subtitle_extractor.asr import AsrBackend, create_backend
from subtitle_extractor.config import Settings
from subtitle_extractor.models import SubtitleDocument

LOGGER = logging.getLogger(__name__)
STATE_VERSION = 1


class SourceFingerprint(BaseModel):
    relative_path: str
    size: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)


class ProfileReference(BaseModel):
    fingerprint: str
    version: int = Field(ge=1)
    model: str
    dtype: str
    language: str


class StateError(BaseModel):
    type: str
    message: str


class ExtractionState(BaseModel):
    version: int = STATE_VERSION
    job_id: str
    source: SourceFingerprint
    profile: ProfileReference
    status: Literal["pending", "processing", "complete", "failed"]
    attempt: int = Field(ge=1)
    output: str = "source.subtitle.json"
    started_at: str
    completed_at: str | None = None
    error: StateError | None = None


@dataclass
class BatchSummary:
    discovered: int = 0
    completed: int = 0
    skipped: int = 0
    failed: int = 0
    busy: int = 0
    deferred: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


class TaskLock:
    def __init__(self, path: Path, stale_seconds: int) -> None:
        self.path = path
        self.stale_seconds = stale_seconds
        self.token = uuid.uuid4().hex
        self.acquired = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                descriptor = os.open(
                    self.path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o644,
                )
            except FileExistsError:
                if not self._is_stale():
                    return False
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                continue

            payload = {
                "token": self.token,
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "started_at": utc_now(),
                "heartbeat_at": utc_now(),
            }
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            self.acquired = True
            return True

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("token") == self.token:
                self.path.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("Could not safely remove task lock: %s", self.path)
        finally:
            self.acquired = False

    def _is_stale(self) -> bool:
        try:
            age_seconds = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return True
        if age_seconds <= self.stale_seconds:
            return False

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True

        if payload.get("host") != socket.gethostname():
            return True
        pid = payload.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False


class BatchExtractor:
    def __init__(
        self,
        settings: Settings,
        backend_factory: Callable[[], AsrBackend] | None = None,
    ) -> None:
        self.settings = settings
        self.input_root = settings.input_dir.expanduser().resolve()
        self.data_root = settings.data_dir.expanduser().resolve()
        self.backend_factory = backend_factory or (lambda: create_backend(settings))
        self._backend: AsrBackend | None = None
        self.profile = build_profile(settings)

    def run(self) -> BatchSummary:
        if not self.input_root.is_dir():
            raise FileNotFoundError(f"Input directory not found: {self.input_root}")
        self._prepare_data_directories()

        media_paths = list(iter_media_files(self.input_root, self.settings.allowed_extensions))
        summary = BatchSummary(discovered=len(media_paths))
        for media_path in media_paths:
            outcome = self._process_media(media_path)
            setattr(summary, outcome, getattr(summary, outcome) + 1)
        return summary

    @property
    def backend(self) -> AsrBackend:
        if self._backend is None:
            self._backend = self.backend_factory()
        return self._backend

    def _prepare_data_directories(self) -> None:
        for name in ("jobs", "locks", "temp", "failed"):
            (self.data_root / name).mkdir(parents=True, exist_ok=True)

    def _process_media(
        self,
        media_path: Path,
    ) -> Literal["completed", "skipped", "failed", "busy", "deferred"]:
        try:
            source = fingerprint_source(media_path, self.input_root)
        except OSError as exc:
            LOGGER.error("Cannot inspect %s: %s", media_path, exc)
            return "failed"

        if not source_is_settled(source, self.settings.file_settle_seconds):
            LOGGER.info("Deferred unsettled media: %s", source.relative_path)
            return "deferred"

        job_id = job_id_for(source.relative_path)
        job_dir = self.data_root / "jobs" / job_id[:2] / job_id
        state_path = job_dir / "extract.state.json"
        output_path = job_dir / "source.subtitle.json"
        previous_state = read_state(state_path)

        if self._can_skip(previous_state, source, output_path):
            LOGGER.info("Skipped completed media: %s", source.relative_path)
            return "skipped"

        same_attempt_series = bool(
            previous_state
            and previous_state.source == source
            and previous_state.profile.fingerprint == self.profile.fingerprint
        )
        if (
            same_attempt_series
            and previous_state is not None
            and previous_state.status == "failed"
            and previous_state.attempt >= self.settings.max_attempts
        ):
            LOGGER.error("Maximum attempts reached for: %s", source.relative_path)
            return "failed"
        attempt = previous_state.attempt + 1 if same_attempt_series and previous_state else 1

        lock = TaskLock(
            self.data_root / "locks" / f"{job_id}.extract.lock",
            self.settings.stale_lock_seconds,
        )
        if not lock.acquire():
            LOGGER.info("Task is already locked: %s", source.relative_path)
            return "busy"

        started_at = utc_now()
        processing_state = ExtractionState(
            job_id=job_id,
            source=source,
            profile=self.profile,
            status="processing",
            attempt=attempt,
            started_at=started_at,
        )
        try:
            current_source = fingerprint_source(media_path, self.input_root)
            if current_source != source:
                LOGGER.info(
                    "Deferred media that changed before processing: %s", source.relative_path
                )
                return "deferred"

            job_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_model(state_path, processing_state)
            document = self.backend.transcribe(media_path, self.settings.language)
            document = SubtitleDocument.model_validate(
                document.model_copy(update={"media_file": source.relative_path})
            )

            current_source = fingerprint_source(media_path, self.input_root)
            if current_source != source:
                raise RuntimeError("Source media changed during transcription")

            atomic_write_model(output_path, document)
            validated_document = SubtitleDocument.model_validate_json(
                output_path.read_text(encoding="utf-8")
            )
            if validated_document.media_file != source.relative_path:
                raise RuntimeError("Published subtitle contains the wrong media path")

            complete_state = processing_state.model_copy(
                update={"status": "complete", "completed_at": utc_now()}
            )
            atomic_write_model(state_path, complete_state)
            LOGGER.info("Completed media: %s", source.relative_path)
            return "completed"
        except Exception as exc:
            LOGGER.exception("Extraction failed for %s", source.relative_path)
            failed_state = processing_state.model_copy(
                update={
                    "status": "failed",
                    "completed_at": utc_now(),
                    "error": StateError(
                        type=type(exc).__name__,
                        message=str(exc).strip()[:500] or "Unknown extraction error",
                    ),
                }
            )
            try:
                job_dir.mkdir(parents=True, exist_ok=True)
                atomic_write_model(state_path, failed_state)
            except OSError:
                LOGGER.exception("Could not persist failed state for %s", source.relative_path)
            return "failed"
        finally:
            lock.release()

    def _can_skip(
        self,
        state: ExtractionState | None,
        source: SourceFingerprint,
        output_path: Path,
    ) -> bool:
        if (
            state is None
            or state.status != "complete"
            or state.source != source
            or state.profile.fingerprint != self.profile.fingerprint
            or state.output != output_path.name
        ):
            return False
        try:
            document = SubtitleDocument.model_validate_json(output_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError):
            return False
        return document.media_file == source.relative_path


def iter_media_files(root: Path, extensions: frozenset[str]) -> Iterator[Path]:
    pending_directories = [root]
    found: list[Path] = []
    while pending_directories:
        directory = pending_directories.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.startswith(".") or entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending_directories.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    path = Path(entry.path)
                    if path.suffix.lower() in extensions:
                        found.append(path)
    yield from sorted(found, key=lambda path: path.relative_to(root).as_posix())


def fingerprint_source(path: Path, root: Path) -> SourceFingerprint:
    relative_path = path.relative_to(root).as_posix()
    stat = os.stat(path, follow_symlinks=False)
    return SourceFingerprint(
        relative_path=relative_path,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def source_is_settled(source: SourceFingerprint, settle_seconds: int) -> bool:
    return time.time_ns() - source.mtime_ns >= settle_seconds * 1_000_000_000


def job_id_for(relative_path: str) -> str:
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()


def build_profile(settings: Settings) -> ProfileReference:
    payload = {
        "profile_version": settings.profile_version,
        "model": model_identity(settings.model),
        "dtype": settings.dtype,
        "device": settings.device,
        "attention": settings.attention,
        "language": settings.language,
        "task": settings.task,
        "schema_version": "subtitle-document/v1",
        "audio_sample_rate": 16000,
        "ffmpeg_chunk_seconds": settings.ffmpeg_chunk_seconds,
    }
    fingerprint = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return ProfileReference(
        fingerprint=f"sha256:{fingerprint}",
        version=settings.profile_version,
        model=Path(settings.model).name,
        dtype=settings.dtype,
        language=settings.language,
    )


def model_identity(model: str) -> dict[str, object]:
    model_path = Path(model).expanduser()
    if not model_path.is_dir():
        return {"identifier": model}

    selected_files: set[Path] = set(model_path.glob("*.safetensors"))
    for name in (
        "config.json",
        "generation_config.json",
        "preprocessor_config.json",
        "tokenizer_config.json",
    ):
        candidate = model_path / name
        if candidate.is_file():
            selected_files.add(candidate)
    files = []
    for path in sorted(selected_files):
        stat = path.stat()
        files.append(
            {
                "path": path.relative_to(model_path).as_posix(),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return {"path": str(model_path.resolve()), "files": files}


def canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_state(path: Path) -> ExtractionState | None:
    try:
        return ExtractionState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return None


def atomic_write_model(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        content = model.model_dump_json(indent=2) + "\n"
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
