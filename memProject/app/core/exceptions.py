# -*- coding: utf-8 -*-
"""
统一异常体系 — 标准错误码 + HTTP 状态码映射。
"""

from typing import Optional


class AppException(Exception):
    """应用基础异常"""
    def __init__(self, code: str, message: str, status_code: int = 500, detail: Optional[dict] = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(message)


# ---- 接入层异常 (4xx) ----

class ValidationError(AppException):
    def __init__(self, message: str = "参数校验失败", detail: Optional[dict] = None,
                 code: str = "VALIDATION_ERROR"):
        super().__init__(code, message, 422, detail)


class AuthenticationError(AppException):
    def __init__(self, message: str = "认证失败"):
        super().__init__("AUTHENTICATION_ERROR", message, 401)


class AuthorizationError(AppException):
    def __init__(self, message: str = "权限不足"):
        super().__init__("AUTHORIZATION_ERROR", message, 403)


class NotFoundError(AppException):
    def __init__(self, message: str = "资源不存在"):
        super().__init__("NOT_FOUND", message, 404)


class ConflictError(AppException):
    def __init__(self, message: str = "资源冲突"):
        super().__init__("CONFLICT", message, 409)


# ---- 服务层异常 ----

class MemoryWriteError(AppException):
    def __init__(self, message: str = "记忆写入失败"):
        super().__init__("MEMORY_WRITE_ERROR", message, 500)


class MemoryRetrievalError(AppException):
    def __init__(self, message: str = "记忆检索失败"):
        super().__init__("MEMORY_RETRIEVAL_ERROR", message, 500)


class MemoryGenerationError(AppException):
    def __init__(self, message: str = "记忆生成失败"):
        super().__init__("MEMORY_GENERATION_ERROR", message, 500)


class LLMServiceError(AppException):
    def __init__(self, message: str = "大模型服务异常"):
        super().__init__("LLM_SERVICE_ERROR", message, 503)


class VectorStoreError(AppException):
    def __init__(self, message: str = "向量库服务异常"):
        super().__init__("VECTOR_STORE_ERROR", message, 503)


class DatabaseError(AppException):
    def __init__(self, message: str = "数据库异常"):
        super().__init__("DATABASE_ERROR", message, 500)


class ServiceDegradedError(AppException):
    """服务降级异常"""
    def __init__(self, message: str = "服务降级中"):
        super().__init__("SERVICE_DEGRADED", message, 503)
