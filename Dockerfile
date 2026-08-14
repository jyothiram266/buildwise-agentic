# Single image that serves the API and, when the frontend has been built, the SPA
# from the same origin. That is what makes one-service hosting (Render, Railway,
# Fly, a single VM) possible without a separate static site and CORS config.
#
# Layer order matters and is deliberate: dependencies install from
# requirements.txt *before* any source is copied, so editing a Python file does not
# reinstall FastAPI. The project itself is never pip-installed — WORKDIR is /app and
# the packages sit directly under it, so they import without a build step. An
# earlier version ran `pip install "."` here and failed, because setuptools looked
# for the `api` package before that directory had been copied.

FROM node:22-alpine AS web
ARG BUILD_WEB=true
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN if [ "$BUILD_WEB" = "true" ]; then npm install --no-audit --no-fund; fi
COPY web/ ./
RUN if [ "$BUILD_WEB" = "true" ]; then npm run build; else mkdir -p dist; fi


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONPATH=/app \
    APP_ENV=dev

# curl is here for the container healthcheck; nothing else is installed, because
# every extra package in a runtime image is a thing to patch later.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, from a flat list, so this layer survives code edits.
COPY requirements.txt requirements-dev.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Test and lint tooling in the image by default. The alternative is telling anyone
# on Windows to build a local Python environment just to run the test suite, which
# defeats the point of shipping a container. Set INSTALL_DEV=false for a lean
# production image.
ARG INSTALL_DEV=true
RUN if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; fi

COPY core/ ./core/
COPY api/ ./api/
COPY agents/ ./agents/
COPY orchestration/ ./orchestration/
COPY connectors/ ./connectors/
COPY retrieval/ ./retrieval/
COPY governance/ ./governance/
COPY llm/ ./llm/
COPY db/ ./db/
COPY scripts/ ./scripts/
COPY eval/ ./eval/
COPY data/ ./data/
COPY tests/ ./tests/
COPY pyproject.toml AGENTS.md README.md Makefile ./

COPY --from=web /web/dist ./web/dist

# Runs unprivileged. The app never needs to write to its own source tree.
RUN useradd --create-home --shell /bin/bash buildwise && chown -R buildwise:buildwise /app
USER buildwise

EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --start-period=40s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
