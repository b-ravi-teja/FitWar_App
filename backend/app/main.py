"""FastAPI application factory. Composition root: wires config, middleware, error
handlers, and routers together. No business logic here — that lives in services/domain.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.database import dispose_engine
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.redis import close_redis


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    yield
    await dispose_engine()
    await close_redis()


def create_app() -> FastAPI:
    # Fail fast: constructing Settings validates every required env var now, at
    # import/boot time, rather than on the first request that happens to need one.
    settings = get_settings()

    app = FastAPI(
        title="FITWAR API",
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.app.debug,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(api_router)

    return app


app = create_app()
