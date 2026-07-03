# -*- coding: utf-8 -*-
"""
FastAPI 应用入口 — 智能体记忆系统（开发阶段）。
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import check_db_connection, create_pgvector_extension
from app.core.logger import setup_logging, get_logger
from app.middleware import LoggingMiddleware, register_exception_handlers, AuthMiddleware
from app.services.mem0_client import mem0_client

settings = get_settings()
setup_logging()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info(f"Starting {settings.app.name} v{settings.app.version}")

    db_ok = await check_db_connection()
    if not db_ok:
        logger.error("Database connection failed")
    else:
        logger.info("Database connection OK")
        await create_pgvector_extension()

    logger.info("Application startup complete")
    yield
    from app.mcp_client import mcp_client as mc
    await mc.close_all()
    logger.info("Application shutting down")


app = FastAPI(
    title=settings.app.name,
    version=settings.app.version,
    docs_url="/docs" if settings.app.debug else None,
    redoc_url="/redoc" if settings.app.debug else None,
    lifespan=lifespan,
)

register_exception_handlers(app)
app.add_middleware(LoggingMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
async def health_check():
    return {"status": "ok", "app": settings.app.name, "version": settings.app.version}


@app.get("/api/v1/health", tags=["system"])
async def api_health_check():
    return {"status": "ok", "database": await check_db_connection()}


from app.api.v1.router import api_router
app.include_router(api_router, prefix="/api/v1")


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.server.host, port=settings.server.port, reload=settings.app.debug)
