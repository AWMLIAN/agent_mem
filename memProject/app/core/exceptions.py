# -*- coding: utf-8 -*-
"""
统一异常体系 — 标准错误码 + HTTP 状态码映射。

错误码格式（5位数字）：
  4xxxx: 客户端错误（参数、认证、权限）
  5xxxx: 服务端错误（数据库、LLM、向量库、MQ）

错误码明细:
  40001 — Token 失效/认证失败
  40002 — 必填字段缺失
  40003 — 参数格式非法
  40004 — 权限不足
  40005 — 资源不存在
  40006 — 资源冲突/重复
  50001 — 记忆写入失败
  50002 — 记忆检索失败
  50003 — 记忆生成失败
  50004 — LLM 服务异常
  50005 — 向量库服务异常
  50006 — 数据库异常
  50007 — MQ 消息投递失败
  50008 — 服务降级中
"""

from typing import Optional


class AppException(Exception):
    """应用基础异常"""
    def __init__(self, code: str, message: str, status_code: int = 500,
                 numeric_code: Optional[int] = None, detail: Optional[dict] = None):
        self.code = code
        self.numeric_code = numeric_code
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(message)


# ---- 接入层异常 (4xx) ----

class ValidationError(AppException):
    def __init__(self, message: str = "参数校验失败", detail: Optional[dict] = None,
                 code: str = "VALIDATION_ERROR", numeric_code: int = 40003):
        super().__init__(code, message, 422, numeric_code, detail)


class AuthenticationError(AppException):
    def __init__(self, message: str = "认证失败"):
        super().__init__("AUTHENTICATION_ERROR", message, 401, 40001)


class AuthorizationError(AppException):
    def __init__(self, message: str = "权限不足"):
        super().__init__("AUTHORIZATION_ERROR", message, 403, 40004)


class NotFoundError(AppException):
    def __init__(self, message: str = "资源不存在"):
        super().__init__("NOT_FOUND", message, 404, 40005)


class ConflictError(AppException):
    def __init__(self, message: str = "资源冲突"):
        super().__init__("CONFLICT", message, 409, 40006)


# ---- 服务层异常 ----

class MemoryWriteError(AppException):
    def __init__(self, message: str = "记忆写入失败"):
        super().__init__("MEMORY_WRITE_ERROR", message, 500, 50001)


class MemoryRetrievalError(AppException):
    def __init__(self, message: str = "记忆检索失败"):
        super().__init__("MEMORY_RETRIEVAL_ERROR", message, 500, 50002)


class MemoryGenerationError(AppException):
    def __init__(self, message: str = "记忆生成失败"):
        super().__init__("MEMORY_GENERATION_ERROR", message, 500, 50003)


class LLMServiceError(AppException):
    def __init__(self, message: str = "大模型服务异常"):
        super().__init__("LLM_SERVICE_ERROR", message, 503, 50004)


class VectorStoreError(AppException):
    def __init__(self, message: str = "向量库服务异常"):
        super().__init__("VECTOR_STORE_ERROR", message, 503, 50005)


class DatabaseError(AppException):
    def __init__(self, message: str = "数据库异常"):
        super().__init__("DATABASE_ERROR", message, 500, 50006)


class ServiceDegradedError(AppException):
    """服务降级异常"""
    def __init__(self, message: str = "服务降级中"):
        super().__init__("SERVICE_DEGRADED", message, 503, 50008)


class MQDeliveryError(AppException):
    """MQ 消息投递失败"""
    def __init__(self, message: str = "MQ 消息投递失败"):
        super().__init__("MQ_DELIVERY_ERROR", message, 500, 50007)
