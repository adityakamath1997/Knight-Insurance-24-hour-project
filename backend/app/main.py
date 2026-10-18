from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.agents.extraction import build_extraction_runner
from app.agents.narrative import (
    NarrativeService,
    NarrativeWriter,
    build_narrative_writer,
)
from app.api import router
from app.persistence.database import create_db_engine
from app.persistence.repository import SubmissionNotFoundError, SubmissionRepository
from app.services.review import Extractor, ReviewService
from app.settings import Settings


def create_app(
    settings: Settings | None = None,
    extractor: Extractor | None = None,
    writer: NarrativeWriter | None = None,
) -> FastAPI:
    """Tests inject fake agents; otherwise real ones are built from settings."""
    settings = settings or Settings()
    repository = SubmissionRepository(create_db_engine(settings.database_path))
    narrative = NarrativeService(repository, writer or build_narrative_writer(settings))

    app = FastAPI(title="Knight Insurance Submission Review")
    app.state.review = ReviewService(
        repository, extractor or build_extraction_runner(settings), narrative
    )
    app.state.narrative = narrative
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.exception_handler(SubmissionNotFoundError)
    def not_found(_request: Request, error: SubmissionNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404, content={"detail": f"Submission {error} not found"}
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
