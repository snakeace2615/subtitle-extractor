import json
import os
import socket
from pathlib import Path

from subtitle_extractor.batch import BatchExtractor, job_id_for
from subtitle_extractor.config import Settings
from subtitle_extractor.models import SubtitleDocument, SubtitleSegment


class RecordingBackend:
    name = "recording"
    model_name = "recording-asr"

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[Path] = []
        self.fail = fail

    def transcribe(self, media_path: Path, language: str) -> SubtitleDocument:
        self.calls.append(media_path)
        if self.fail:
            raise RuntimeError("synthetic ASR failure")
        return SubtitleDocument(
            media_file=str(media_path),
            source_language=language,
            segments=[SubtitleSegment(id=0, start=0, end=1.5, text="Hello")],
        )


class MutatingBackend(RecordingBackend):
    def transcribe(self, media_path: Path, language: str) -> SubtitleDocument:
        document = super().transcribe(media_path, language)
        media_path.write_bytes(media_path.read_bytes() + b" changed")
        return document


def make_settings(input_dir: Path, data_dir: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "backend": "mock",
        "model": "mock-asr",
        "input_dir": input_dir,
        "data_dir": data_dir,
        "file_settle_seconds": 0,
        "language": "english",
    }
    values.update(overrides)
    return Settings(**values)


def output_path(data_dir: Path, relative_path: str) -> Path:
    job_id = job_id_for(relative_path)
    return data_dir / "jobs" / job_id[:2] / job_id / "source.subtitle.json"


def test_recursive_scan_processes_nested_media_and_skips_hidden(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    data_dir = tmp_path / "data"
    nested_video = input_dir / "course" / "part 1" / "lesson.mp4"
    nested_video.parent.mkdir(parents=True)
    nested_video.write_bytes(b"video")
    second_video = input_dir / "overview.MKV"
    second_video.write_bytes(b"video")
    hidden_video = input_dir / ".cache" / "hidden.mp4"
    hidden_video.parent.mkdir()
    hidden_video.write_bytes(b"hidden")
    (input_dir / "notes.txt").write_text("not media", encoding="utf-8")

    backend = RecordingBackend()
    summary = BatchExtractor(
        make_settings(input_dir, data_dir),
        backend_factory=lambda: backend,
    ).run()

    assert summary.discovered == 2
    assert summary.completed == 2
    assert [path.relative_to(input_dir).as_posix() for path in backend.calls] == [
        "course/part 1/lesson.mp4",
        "overview.MKV",
    ]
    document = SubtitleDocument.model_validate_json(
        output_path(data_dir, "course/part 1/lesson.mp4").read_text(encoding="utf-8")
    )
    assert document.media_file == "course/part 1/lesson.mp4"


def test_second_scan_skips_completed_media_without_loading_backend(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    data_dir = tmp_path / "data"
    input_dir.mkdir()
    (input_dir / "demo.mp4").write_bytes(b"video")
    settings = make_settings(input_dir, data_dir)
    first_backend = RecordingBackend()

    first = BatchExtractor(settings, backend_factory=lambda: first_backend).run()
    second = BatchExtractor(
        settings,
        backend_factory=lambda: (_ for _ in ()).throw(AssertionError("backend loaded")),
    ).run()

    assert first.completed == 1
    assert second.skipped == 1
    assert len(first_backend.calls) == 1


def test_source_change_reprocesses_completed_media(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    data_dir = tmp_path / "data"
    input_dir.mkdir()
    media_path = input_dir / "demo.mp4"
    media_path.write_bytes(b"first")
    settings = make_settings(input_dir, data_dir)
    backend = RecordingBackend()

    BatchExtractor(settings, backend_factory=lambda: backend).run()
    media_path.write_bytes(b"second version")
    summary = BatchExtractor(settings, backend_factory=lambda: backend).run()

    assert summary.completed == 1
    assert len(backend.calls) == 2


def test_profile_change_reprocesses_completed_media(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    data_dir = tmp_path / "data"
    input_dir.mkdir()
    (input_dir / "demo.mp4").write_bytes(b"video")
    backend = RecordingBackend()

    BatchExtractor(
        make_settings(input_dir, data_dir, profile_version=1),
        backend_factory=lambda: backend,
    ).run()
    summary = BatchExtractor(
        make_settings(input_dir, data_dir, profile_version=2),
        backend_factory=lambda: backend,
    ).run()

    assert summary.completed == 1
    assert len(backend.calls) == 2


def test_corrupt_output_is_not_treated_as_complete(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    data_dir = tmp_path / "data"
    input_dir.mkdir()
    (input_dir / "demo.mp4").write_bytes(b"video")
    settings = make_settings(input_dir, data_dir)
    backend = RecordingBackend()

    BatchExtractor(settings, backend_factory=lambda: backend).run()
    output_path(data_dir, "demo.mp4").write_text("{broken", encoding="utf-8")
    summary = BatchExtractor(settings, backend_factory=lambda: backend).run()

    assert summary.completed == 1
    assert len(backend.calls) == 2


def test_failure_records_state_and_stops_after_max_attempts(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    data_dir = tmp_path / "data"
    input_dir.mkdir()
    (input_dir / "demo.mp4").write_bytes(b"video")
    settings = make_settings(input_dir, data_dir, max_attempts=1)
    backend = RecordingBackend(fail=True)

    first = BatchExtractor(settings, backend_factory=lambda: backend).run()
    second = BatchExtractor(settings, backend_factory=lambda: backend).run()
    state_path = output_path(data_dir, "demo.mp4").with_name("extract.state.json")
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert first.failed == 1
    assert second.failed == 1
    assert len(backend.calls) == 1
    assert state["status"] == "failed"
    assert state["error"]["type"] == "RuntimeError"


def test_unsettled_media_is_deferred_without_loading_backend(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    data_dir = tmp_path / "data"
    input_dir.mkdir()
    (input_dir / "uploading.mp4").write_bytes(b"video")

    summary = BatchExtractor(
        make_settings(input_dir, data_dir, file_settle_seconds=3600),
        backend_factory=lambda: (_ for _ in ()).throw(AssertionError("backend loaded")),
    ).run()

    assert summary.deferred == 1


def test_active_lock_prevents_duplicate_processing(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    data_dir = tmp_path / "data"
    input_dir.mkdir()
    (input_dir / "demo.mp4").write_bytes(b"video")
    job_id = job_id_for("demo.mp4")
    lock_path = data_dir / "locks" / f"{job_id}.extract.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps({"host": socket.gethostname(), "pid": os.getpid()}),
        encoding="utf-8",
    )

    summary = BatchExtractor(
        make_settings(input_dir, data_dir),
        backend_factory=lambda: (_ for _ in ()).throw(AssertionError("backend loaded")),
    ).run()

    assert summary.busy == 1


def test_stale_lock_is_recovered(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    data_dir = tmp_path / "data"
    input_dir.mkdir()
    (input_dir / "demo.mp4").write_bytes(b"video")
    job_id = job_id_for("demo.mp4")
    lock_path = data_dir / "locks" / f"{job_id}.extract.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps({"host": socket.gethostname(), "pid": 999_999_999}),
        encoding="utf-8",
    )
    os.utime(lock_path, (1, 1))
    backend = RecordingBackend()

    summary = BatchExtractor(
        make_settings(input_dir, data_dir, stale_lock_seconds=1),
        backend_factory=lambda: backend,
    ).run()

    assert summary.completed == 1
    assert not lock_path.exists()


def test_source_changed_during_transcription_is_not_published(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    data_dir = tmp_path / "data"
    input_dir.mkdir()
    (input_dir / "demo.mp4").write_bytes(b"video")
    backend = MutatingBackend()

    summary = BatchExtractor(
        make_settings(input_dir, data_dir),
        backend_factory=lambda: backend,
    ).run()
    source_output = output_path(data_dir, "demo.mp4")
    state = json.loads(source_output.with_name("extract.state.json").read_text(encoding="utf-8"))

    assert summary.failed == 1
    assert not source_output.exists()
    assert state["status"] == "failed"
    assert "changed during transcription" in state["error"]["message"]
