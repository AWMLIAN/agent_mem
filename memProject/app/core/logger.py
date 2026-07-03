# -*- coding: utf-8 -*-
"""
日志系统 — 基于 Loguru 的结构化日志。
"""

import sys
from pathlib import Path

from loguru import logger

from app.core.config import get_settings

settings = get_settings()


def setup_logging() -> None:
    """初始化全局日志配置"""
    logger.remove()

    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    if settings.logging.output in ("console", "both"):
        logger.add(
            sys.stdout,
            level=settings.logging.level,
            format=log_format,
            colorize=True,
        )

    if settings.logging.output in ("file", "both"):
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        logger.add(
            log_dir / "app_{time:YYYY-MM-DD}.log",
            level=settings.logging.level,
            format=log_format,
            rotation="00:00",
            retention="30 days",
            encoding="utf-8",
        )

    logger.info(f"Logging initialized: level={settings.logging.level}, output={settings.logging.output}")


def get_logger(name: str):
    """获取带模块名的 logger"""
    return logger.bind(module=name)
