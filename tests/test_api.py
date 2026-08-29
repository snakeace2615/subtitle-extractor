from pathlib import Path

import httpx
import pytest

from subtitle_extractor.api import create_app, get_api_settings
from subtitle_extractor.config import Settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def build_app(input_dir: Path):
    app = create_app()
    settings = Settings(
        backend="mock",
        model="mock-asr",
        input_dir=input_dir,
        file_settle_seconds=0,
    )

    async def override_settings() -> Settings:
        return settings

    app.dependency_overrides[get_api_settings] = override_settings
    return app


@pytest.mark.anyio
async def test_health_reports_configured_backend(tmp_path: Path) -> None:
    app = build_app(tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["backend"] == "mock"


@pytest.mark.anyio
async def test_transcription_accepts_media_inside_input_root(tmp_path: Path) -> None:
    media_path = tmp_path / "nested" / "demo.mp4"
    media_path.parent.mkdir()
    media_path.write_bytes(b"video")
    app = build_app(tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/transcriptions",
            json={"media_path": str(media_path), "language": "english"},
        )

    assert response.status_code == 200
    assert response.json()["document"]["source_language"] == "english"


@pytest.mark.anyio
async def test_transcription_rejects_media_outside_input_root(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    media_path = tmp_path / "outside.mp4"
    media_path.write_bytes(b"video")
    app = build_app(input_dir)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/transcriptions",
            json={"media_path": str(media_path), "language": "english"},
        )

    assert response.status_code == 403
