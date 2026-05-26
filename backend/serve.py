"""FastAPI app for JobPulse.

Mounts:
  * /health
  * /api/v1/jobs            (list, get, CSV export)
  * /api/v1/companies       (CRUD, bulk import, manual scrape trigger)
  * /api/v1/scrape-runs     (observability)
  * /api/v1/stats           (dashboard header + per-company health)
  * /                       (built frontend, when frontend/dist exists)
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import companies_router, jobs_router, scrape_runs_router, stats_router
from .config import settings
from .migrations import upgrade_to_head


def create_app() -> FastAPI:
    upgrade_to_head()
    app = FastAPI(title="JobPulse", version="0.1.0")

    # Local-only by default. CORS is permissive on localhost so the Vite dev
    # server (port 5173) can hit the API during frontend development. In
    # production we serve the built frontend from the same origin so CORS is
    # effectively unused.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            f"http://{settings.host}:{settings.port}",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "db": settings.db_path.name, "version": app.version}

    api_prefix = "/api/v1"
    app.include_router(jobs_router, prefix=api_prefix)
    app.include_router(companies_router, prefix=api_prefix)
    app.include_router(scrape_runs_router, prefix=api_prefix)
    app.include_router(stats_router, prefix=api_prefix)

    if settings.frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(settings.frontend_dist), html=True), name="frontend")

    return app


def run_serve() -> None:
    import uvicorn

    uvicorn.run(
        "backend.serve:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run_serve()
