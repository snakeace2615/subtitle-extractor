from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException

from subtitle_extractor.asr import AsrBackend, create_backend
from subtitle_extractor.config import Settings, get_settings
from subtitle_extractor.models import TranscriptionRequest, TranscriptionResponse


async def get_api_settings() -> Settings:
    return get_settings()


SettingsDependency = Annotated[Settings, Depends(get_api_settings)]


def build_backend(settings: Settings) -> AsrBackend:
    return create_backend(settings)


def create_app() -> FastAPI:
    app = FastAPI(title="Subtitle Extractor", version="0.1.0")
    backend_cache: dict[tuple[str, ...], AsrBackend] = {}

    def cached_backend(settings: Settings) -> AsrBackend:
        key = (
            settings.backend,
            settings.model,
            settings.device,
            settings.dtype,
            settings.attention,
            settings.task,
        )
        if key not in backend_cache:
            backend_cache[key] = build_backend(settings)
        return backend_cache[key]

    @app.get("/health")
    async def health(settings: SettingsDependency) -> dict[str, str]:
        return {"status": "ok", "backend": settings.backend, "model": settings.model}

    @app.post("/v1/transcriptions", response_model=TranscriptionResponse)
    async def transcribe(
        request: TranscriptionRequest,
        settings: SettingsDependency,
    ) -> TranscriptionResponse:
        media_path = request.resolved_media_path()
        if not media_path.is_file():
            raise HTTPException(status_code=404, detail=f"Media file not found: {media_path}")
        input_root = settings.input_dir.expanduser().resolve()
        try:
            media_path.relative_to(input_root)
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail=f"Media path is outside the configured input directory: {input_root}",
            ) from exc
        try:
            backend = cached_backend(settings)
        except RuntimeError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        document = backend.transcribe(media_path, request.language)
        return TranscriptionResponse(
            backend=backend.name,
            model=backend.model_name,
            document=document,
        )

    return app


app = create_app()
