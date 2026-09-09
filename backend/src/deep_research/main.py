"""Run the v2 FastAPI application independently of the legacy agent."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router


def create_app() -> FastAPI:
    """Create an application using the same HTTP style as the legacy server."""
    app = FastAPI(title="HelloAgents Deep Researcher v2")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.get("/healthz")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
