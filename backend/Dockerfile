# Multi-stage so the runtime image carries neither the compilers nor the dev tooling.
# The previous single-stage image installed `.[dev]` (pytest, ruff, mypy) and ran
# `uvicorn --reload` as root — a development server shipped as the production artifact.
FROM python:3.12-slim AS builder

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
# Runtime dependencies only — no `[dev]` extra. Test and lint tooling has no business
# in an image that serves traffic.
RUN pip install --no-cache-dir --prefix=/install .


FROM python:3.12-slim AS runtime

# curl is kept for the container healthcheck; nothing else from the build stage carries over.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 fitwar

WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY pyproject.toml ./

# Never root: a container escape should not start with uid 0, and nothing here needs it.
USER fitwar

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# No --reload. Workers are process-level parallelism; the app holds no in-process state
# that a second worker would break (sessions are per-request, realtime fans out through
# Redis), which is what makes this safe.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
