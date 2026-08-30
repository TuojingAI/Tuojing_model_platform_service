from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .registry import (
    CopyPermissionError,
    InvalidSourceError,
    MetadataError,
    ModelRegistry,
    RegistryError,
    VersionConflictError,
)
from .schemas import QueryRequest, QueryResponse, ReleaseRequest, ReleaseResponse


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    registry = ModelRegistry(resolved_settings)
    app = FastAPI(
        title="Tuojing Model Platform Service",
        version="0.1.0",
    )
    app.state.registry = registry

    @app.exception_handler(VersionConflictError)
    def handle_conflict(_request: Request, error: VersionConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(CopyPermissionError)
    def handle_copy_permission(
        _request: Request, error: CopyPermissionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={
                "detail": str(error),
                "suggested_command": error.suggested_command,
            },
        )

    @app.exception_handler(InvalidSourceError)
    def handle_source(_request: Request, error: InvalidSourceError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.exception_handler(MetadataError)
    def handle_metadata(_request: Request, error: MetadataError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(error)})

    @app.exception_handler(RegistryError)
    def handle_registry(_request: Request, error: RegistryError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "meta_dir": str(resolved_settings.meta_dir),
            "release_dir": str(resolved_settings.release_dir),
            "workspace_root": str(resolved_settings.workspace_root),
        }

    @app.post("/api/v1/models/release", response_model=ReleaseResponse)
    def release_model(payload: ReleaseRequest) -> ReleaseResponse:
        return ReleaseResponse(model=registry.release(payload))

    @app.post("/api/v1/models/query", response_model=QueryResponse)
    def query_models(payload: QueryRequest) -> QueryResponse:
        return QueryResponse(models=registry.query(payload))

    return app
