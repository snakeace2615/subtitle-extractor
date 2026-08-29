from fastapi import Depends, FastAPI, HTTPException

from subtitle_extractor.asr import AsrBackend, MockAsrBackend
from subtitle_extractor.config import Settings, get_settings
from subtitle_extractor.models import TranscriptionRequest, TranscriptionResponse


def build_backend(settings: Settings) -> AsrBackend:
    if settings.backend == "mock":
        return MockAsrBackend()
    raise RuntimeError(f"ASR backend is not implemented: {settings.backend}")


def create_app() -> FastAPI:
    app = FastAPI(title="Subtitle Extractor", version="0.1.0")

    @app.get("/health")
    def health(settings: Settings = Depends(get_settings)) -> dict[str, str]:
        return {"status": "ok", "backend": settings.backend, "model": settings.model}

    @app.post("/v1/transcriptions", response_model=TranscriptionResponse)
    def transcribe(
        request: TranscriptionRequest,
        settings: Settings = Depends(get_settings),
    ) -> TranscriptionResponse:
        media_path = request.resolved_media_path()
        if not media_path.is_file():
            raise HTTPException(status_code=404, detail=f"Media file not found: {media_path}")
        try:
            backend = build_backend(settings)
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

