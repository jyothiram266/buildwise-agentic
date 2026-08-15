"""The API application.

Also serves the built frontend from `web/dist` when it exists, so the whole system
can run as one container on a single port. That matters for the deployment story:
a reviewer with a free Render or Railway account can host this without configuring
a separate static site.

Startup validates configuration, prompts and policies before accepting traffic.
Failing at boot is the correct behaviour for a missing prompt version — the
alternative is discovering it on a customer's case.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from api.config import configure_logging, get_logger, get_settings, validate_runtime
from api.deps import ScopeDep
from api.schemas.requests import TokenRequest
from api.schemas.responses import ActorView, TokenResponse
from connectors import registry
from core.errors import BuildWiseError, ScopeViolationError
from db import pool
from governance import rbac
from governance.policy_registry import REQUIRED_PROMPTS, get_registry

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    validate_runtime()
    get_registry().validate_all(REQUIRED_PROMPTS)
    await pool.get_pool()
    mode = await pool.dense_mode()
    log.info(
        "api_started",
        env=settings.app_env,
        llm_provider=settings.llm_provider,
        embeddings=settings.embedding_provider,
        dense_mode=mode,
    )
    yield
    await pool.close_pool()


app = FastAPI(
    title="BuildWise Agentic AI Support",
    version="1.0.0",
    description=(
        "Multi-agent support system for real estate sales, documentation, construction "
        "status, maintenance and contractor coordination."
    ),
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.exception_handler(BuildWiseError)
async def buildwise_error_handler(request: Request, exc: BuildWiseError) -> JSONResponse:
    """Typed errors become typed responses; nothing leaks a stack trace."""
    code = status.HTTP_403_FORBIDDEN if isinstance(exc, ScopeViolationError) else status.HTTP_400_BAD_REQUEST
    log.warning("request_failed", path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=code, content=exc.to_dict())


meta = APIRouter(tags=["meta"])


@meta.get("/health")
async def health() -> dict:
    """Liveness plus dependency status. Used by docker-compose and the platform.

    Reads the dense mode live rather than reporting what was cached at startup: the
    API boots before migrations run, so a value captured at startup can be stale for
    the life of the process.
    """
    db = await pool.healthcheck()
    return {
        "ok": bool(db.get("ok")),
        "env": settings.app_env,
        "llm_provider": settings.llm_provider,
        "embedding_provider": settings.embedding_provider,
        "database": db,
    }


@meta.get("/api/health/connectors")
async def connector_health() -> dict:
    return {"connectors": await registry.health_all()}


@meta.get("/api/actors", response_model=list[ActorView])
async def actors() -> list[ActorView]:
    """Identity directory, for the demo role switcher."""
    return [ActorView(**{k: v for k, v in row.items()}) for row in await rbac.list_actors()]


@meta.post("/api/auth/token", response_model=TokenResponse)
async def token(body: TokenRequest) -> TokenResponse:
    """Mint a demo token for an actor in the directory.

    Deliberately unauthenticated and deliberately obvious: this stands in for SSO,
    and the runbook says to remove it before any real deployment.
    """
    if settings.app_env == "prod":
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "the demo token endpoint is disabled outside dev"
        )
    try:
        scope = await rbac.scope_for_actor(body.actor_id)
    except ScopeViolationError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc
    row = next((a for a in await rbac.list_actors() if a["actor_id"] == body.actor_id), {})
    return TokenResponse(
        token=rbac.issue_token(body.actor_id),
        actor=ActorView(
            actor_id=scope.actor_id,
            display_name=str(row.get("display_name", scope.actor_id)),
            role=scope.role.value,
            booking_ids=scope.booking_ids,
            unit_ids=scope.unit_ids,
            project_ids=scope.project_ids,
            work_package_ids=scope.work_package_ids,
        ),
        capabilities={
            "collections": rbac.readable_collections(scope.role),
            "may_approve": rbac.may_approve(scope.role),
        },
    )


@meta.get("/api/me")
async def me(scope: ScopeDep) -> dict:
    return {
        "actor_id": scope.actor_id,
        "role": scope.role.value,
        "scope": scope.model_dump(mode="json"),
        "capabilities": {
            "collections": rbac.readable_collections(scope.role),
            "may_approve": rbac.may_approve(scope.role),
        },
    }


app.include_router(meta)

from api.routes import audit as audit_routes  # noqa: E402
from api.routes import cases as case_routes  # noqa: E402
from api.routes import dashboard as dashboard_routes  # noqa: E402
from api.routes import intake as intake_routes  # noqa: E402
from api.routes import review as review_routes  # noqa: E402

app.include_router(intake_routes.router)
app.include_router(case_routes.router)
app.include_router(review_routes.router)
app.include_router(dashboard_routes.router)
app.include_router(audit_routes.router)


# ---------------------------------------------------------------------------
# Static frontend (single-container deployment)
# ---------------------------------------------------------------------------

DIST = Path(settings.web_dist_dir)

#: A `dist` directory can exist and be empty — the Dockerfile creates one when
#: BUILD_WEB=false so the COPY stage has something to copy. Testing for the
#: directory alone was a real bug: StaticFiles raises at construction when its
#: target is missing, so an empty dist killed the API process before uvicorn ever
#: bound a port. The presence of index.html is what actually means "a build exists".
SPA_BUILT = (DIST / "index.html").is_file()

if SPA_BUILT:
    from fastapi.staticfiles import StaticFiles

    # Vite emits hashed files into assets/, but a build with no static imports may
    # not create it, so mounting is conditional on the directory being real.
    assets = DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        """Serve the SPA, letting the client router own unknown paths.

        API routes are registered before this catch-all, so they win. An unknown
        /api path still needs to 404 as an API error rather than returning HTML,
        which a client would try to parse as JSON.
        """
        if full_path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown API route")
        candidate = DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")

else:

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {
            "service": "buildwise-api",
            "docs": "/docs",
            "health": "/health",
            "note": (
                "The frontend is not built. Run `make web-build`, or use the Vite dev server "
                "on port 3000."
            ),
        }
