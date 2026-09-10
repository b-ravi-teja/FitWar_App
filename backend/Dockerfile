# Multi-stage so the runtime image carries neither the compilers nor the dev tooling.
# The previous single-stage image installed `.[dev]` (pytest, ruff, mypy) and ran
# `uvicorn --reload` as root — a development server shipped as the production artifact.
FROM python:3.12-slim AS builder

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements.lock ./
COPY app ./app
# Two steps on purpose. The lock is fully pinned and hash-verified, so the dependency
# set is byte-identical on every build — `pip install .` alone would re-resolve the
# `>=` ranges in pyproject.toml and could ship a different transitive tree to staging
# than the one CI tested. `--require-hashes` also means a compromised or substituted
# package fails the build rather than being installed.
RUN pip install --no-cache-dir --prefix=/install --require-hashes -r requirements.lock
# The app itself, with its dependencies already satisfied above.
RUN pip install --no-cache-dir --prefix=/install --no-deps .


FROM python:3.12-slim AS runtime

# curl is kept for the container healthcheck; nothing else from the build stage carries over.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 fitwar

WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
COPY alembic ./alembic
# Post-deployment smoke test. In the image on purpose: the check that a deployment
# works should run from the same artifact that was deployed, not from a copy of the
# repo that happens to be checked out on a CI runner.
COPY scripts ./scripts
COPY alembic.ini ./
COPY pyproject.toml ./

# Never root: a container escape should not start with uid 0, and nothing here needs it.
USER fitwar

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# PORT is what the platform tells the container to listen on (Render sets it; Compose
# and `docker run` fall back to this default). WEB_CONCURRENCY is uvicorn's own
# convention for worker count — a 512MB instance runs one worker, not two.
ENV PORT=8000 WEB_CONCURRENCY=2

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT}/health" || exit 1

# No --reload. Workers are process-level parallelism; the app holds no in-process state
# that a second worker would break (sessions are per-request, realtime fans out through
# Redis), which is what makes this safe.
#
# `exec` matters: without it the shell stays PID 1 and SIGTERM never reaches uvicorn, so
# the platform's graceful-shutdown window elapses and the container is killed mid-request.
# The shell form is needed at all only because ${PORT} must be expanded at runtime.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY}"]
