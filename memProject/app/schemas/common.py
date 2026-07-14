# -*- coding: utf-8 -*-
"""
统一响应格式 — 所有 API 返回 JSON 遵循此规范。
"""

from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """标准 API 响应"""
    code: int = Field(default=0, description="业务状态码，0 表示成功")
    message: str = Field(default="ok", description="状态描述")
    data: Optional[T] = Field(default=None, description="响应数据")


class PaginatedData(BaseModel, Generic[T]):
    """分页数据"""
    items: list[T] = Field(default_factory=list)
    total: int = Field(default=0)
    page: int = Field(default=1)
    page_size: int = Field(default=20)


class ErrorResponse(BaseModel):
    """错误响应"""
    code: int = Field(default=-1)
    message: str = Field(default="error")
    error_code: str = Field(default="INTERNAL_ERROR")
    detail: Optional[dict] = Field(default=None)
    trace_id: Optional[str] = Field(default=None)


def ok(data: Any = None, message: str = "ok") -> dict:
    """快速构造成功响应"""
    return {"code": 0, "message": message, "data": data}


def error(
    message: str = "error",
    code: int = -1,
    data: Any = None,
    error_code: str | None = None,
) -> dict:
    """快速构造错误响应。前端先看 code != 0，后续可按 error_code 细分。"""
    resp = {"code": code, "message": message, "data": data}
    if error_code:
        resp["error_code"] = error_code
    return resp


def paginated(items: list, total: int, page: int, page_size: int) -> dict:
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }
