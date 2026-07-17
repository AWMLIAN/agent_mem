# -*- coding: utf-8 -*-
"""
Result Waiter — Redis Pub/Sub 伪同步等待机制（核心改动 方案二）。

职责:
  - wait_for_result(request_id, timeout): 订阅 Redis channel，阻塞等待 Consumer 处理结果
  - publish_result(request_id, results): 将 Consumer 处理结果发布到 Redis
  - 超时降级：等待超时后返回 SKIP 事件

使用流程:
  1. /write 端点投递 MQ 消息后，调用 wait_for_result(request_id)
  2. Consumer 处理完消息后，调用 publish_result(request_id, results)
  3. wait_for_result 收到结果后返回给 /write 端点

降级策略:
  - Redis 不可用 → 立即返回 SKIP
  - 等待超时 → 返回 SKIP（不阻塞客户端）
"""

import asyncio
import json

from app.core.config import get_settings
from app.core.logger import get_logger

logger = get_logger("result_waiter")

settings = get_settings()

# Redis channel 前缀
CHANNEL_PREFIX = "memory:result:"


async def _get_redis_client():
    """创建 Redis 异步客户端（每次调用创建新连接）"""
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(
            settings.redis.url,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        await client.ping()
        return client
    except ImportError:
        logger.warning("redis 库未安装，无法使用 Result Waiter")
        return None
    except Exception as e:
        logger.warning(f"Redis 连接失败（将降级）: {e}")
        return None


async def publish_result(request_id: str, results: list[dict]) -> bool:
    """
    发布 Consumer 处理结果到 Redis Pub/Sub。

    Args:
        request_id: 请求 ID
        results: 处理结果列表 [{id, memory, event}, ...]

    Returns:
        True 发布成功，False 失败
    """
    redis_client = await _get_redis_client()
    if redis_client is None:
        return False

    try:
        channel = f"{CHANNEL_PREFIX}{request_id}"
        payload = json.dumps({"results": results, "status": "completed"})
        await redis_client.publish(channel, payload)
        # 同时写入 key（作为 fallback—5min TTL）
        await redis_client.setex(
            f"{CHANNEL_PREFIX}{request_id}:data",
            settings.redis.result_ttl,
            payload,
        )
        logger.debug(f"结果已发布到 Redis: request_id={request_id}")
        return True
    except Exception as e:
        logger.warning(f"Redis 结果发布失败: {e}")
        return False
    finally:
        try:
            await redis_client.aclose()
        except Exception:
            pass


async def wait_for_result(request_id: str, timeout: float | None = None) -> list[dict] | None:
    """
    等待 Consumer 处理结果（伪同步）。

    订阅 Redis channel，阻塞等待直到:
      - 收到 Consumer 发布的结果 → 返回 [{id, memory, event}, ...]
      - 超时 → 返回 None（调用方应返回 SKIP）
      - Redis 不可用 → 返回 None

    Args:
        request_id: 请求 ID
        timeout: 等待超时秒数（默认使用配置值）

    Returns:
        None 表示降级（应返回 SKIP），list[dict] 表示处理结果
    """
    if timeout is None:
        timeout = settings.redis.result_poll_timeout

    redis_client = await _get_redis_client()
    if redis_client is None:
        logger.warning(f"Redis 不可用，跳过等待: request_id={request_id}")
        return None

    try:
        channel = f"{CHANNEL_PREFIX}{request_id}"
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)

        try:
            # 阻塞等待消息
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        results = data.get("results", [])
                        logger.info(
                            f"收到结果: request_id={request_id}, "
                            f"results={len(results)}"
                        )
                        return results
                    except json.JSONDecodeError:
                        logger.warning(f"无法解析 Redis 消息: {message['data'][:200]}")
                        return None

                # 每次循环检查超时（pubsub.listen 本身不超时，用 timeout context 包装）
                # 实际上 listen() 会阻塞，所以我们需要用 wait_for...
        except asyncio.CancelledError:
            raise

        # 这里实际上不太能达到，因为 listen() 会无限阻塞
        return None
    except Exception as e:
        logger.warning(f"Redis 等待异常: request_id={request_id}, error={e}")
        return None
    finally:
        try:
            await redis_client.aclose()
        except Exception:
            pass


async def wait_for_result_with_timeout(
    request_id: str, timeout: float | None = None
) -> list[dict] | None:
    """
    带超时的等待 — 调用方使用此方法。

    在 timeout 秒内等待结果；超时/Redis 不可用返回 None，
    由调用方决定降级行为并在响应中标记（不再静默伪造 SKIP 结果）。
    """
    if timeout is None:
        timeout = settings.redis.result_poll_timeout

    try:
        result = await asyncio.wait_for(
            wait_for_result(request_id, timeout=timeout),
            timeout=timeout + 0.5,  # 给内部一些余地
        )
        return result
    except asyncio.TimeoutError:
        logger.info(f"等待结果超时 ({timeout}s): request_id={request_id}, 交由调用方降级")
        return None
    except Exception as e:
        logger.warning(f"等待结果异常: request_id={request_id}, error={e}")
        return None


# 检查 Redis 是否可用
async def is_redis_available() -> bool:
    """检查 Redis 服务是否可用"""
    redis_client = await _get_redis_client()
    if redis_client is None:
        return False
    try:
        await redis_client.aclose()
    except Exception:
        pass
    return redis_client is not None
