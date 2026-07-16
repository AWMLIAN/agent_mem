# -*- coding: utf-8 -*-
"""
MQ 生产者 — AIOKafka Producer 单例。

职责:
  - 维护 Kafka 连接（启动时初始化，关闭时释放）
  - publish_memory_write(): 投递记忆写入消息到 memory.write
  - publish_memory_result(): 发布处理结果到 memory.result
  - 优雅降级: Kafka 不可用时返回 False，记录错误

使用:
  from app.services.mq_producer import MQProducer

  producer = MQProducer()
  await producer.start()
  ok = await producer.publish_memory_write(request_id, user_id, body_dict)
  await producer.stop()
"""

import asyncio
import json
import time as time_module

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from app.core.config import get_settings
from app.core.logger import get_logger

logger = get_logger("mq_producer")


class MQProducer:
    """AIOKafka 生产者单例"""

    def __init__(self):
        self._producer: AIOKafkaProducer | None = None
        self._started = False
        self._settings = get_settings()

    async def start(self) -> None:
        """启动 Kafka 连接"""
        if self._started:
            return

        try:
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self._settings.kafka.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                acks="all",
                compression_type="gzip",
                max_request_size=1048576,
                linger_ms=5,
                request_timeout_ms=5000,
                metadata_max_age_ms=3000,  # 快速检测 Kafka 是否可达
            )
            await asyncio.wait_for(
                self._producer.start(),
                timeout=3.0  # 3 秒超时，防止启动时长时间阻塞
            )
            self._started = True
            logger.info(f"Kafka Producer 已连接: {self._settings.kafka.bootstrap_servers}")
        except asyncio.TimeoutError:
            logger.warning(f"Kafka 连接超时(3s): {self._settings.kafka.bootstrap_servers} — Kafka 可能未运行")
            self._started = False
        except KafkaError as e:
            logger.warning(f"Kafka Producer 连接失败: {e} — Kafka 可能未运行")
            self._started = False
        except Exception as e:
            logger.error(f"Kafka Producer 初始化异常: {e}")
            self._started = False

    async def stop(self) -> None:
        """关闭 Kafka 连接"""
        if self._producer and self._started:
            try:
                await self._producer.stop()
                self._started = False
                logger.info("Kafka Producer 已关闭")
            except Exception as e:
                logger.warning(f"Kafka Producer 关闭异常: {e}")

    @property
    def is_available(self) -> bool:
        return self._started and self._producer is not None

    async def publish_memory_write(
        self,
        request_id: str,
        user_id: str,
        agent_id: str,
        body_dict: dict,
    ) -> bool:
        """
        投递记忆写入消息到 memory.write 主题。

        Args:
            request_id: 异步请求 ID
            user_id: 用户标识（作为分区键）
            agent_id: 智能体标识
            body_dict: 请求体字典（已验证/标准化）

        Returns:
            True 投递成功，False 投递失败
        """
        if not self.is_available:
            logger.warning("Kafka Producer 不可用，跳过投递")
            return False

        message = {
            "request_id": request_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "body": body_dict,
            "timestamp": time_module.time(),
        }

        topic = self._settings.kafka.topic_memory_write

        try:
            # send() 是 async def，返回 coroutine → 用 wait_for 加超时
            record_metadata = await asyncio.wait_for(
                self._producer.send(topic=topic, key=user_id, value=message),
                timeout=5.0,
            )
            partition = getattr(record_metadata, "partition", "?")
            logger.info(
                f"Kafka 消息已投递: topic={topic}, request_id={request_id}, "
                f"partition={partition}"
            )
            return True
        except asyncio.TimeoutError:
            logger.warning(f"Kafka 投递超时(5s): topic={topic}, request_id={request_id}")
            return False
        except KafkaError as e:
            logger.error(f"Kafka 投递失败: topic={topic}, request_id={request_id}, error={e}")
            self._started = False  # 标记不可用
            return False
        except Exception as e:
            logger.error(f"Kafka 投递未知异常: {e}")
            return False

    async def publish_memory_result(
        self,
        request_id: str,
        user_id: str,
        results: list[dict],
        status: str = "completed",
    ) -> bool:
        """
        发布处理结果到 memory.result 主题。

        Args:
            request_id: 对应的请求 ID
            user_id: 用户标识
            results: 处理结果列表 [{id, memory, event}, ...]
            status: 处理状态 (completed / failed)

        Returns:
            True 发布成功
        """
        if not self.is_available:
            return False

        message = {
            "request_id": request_id,
            "user_id": user_id,
            "results": results,
            "status": status,
            "timestamp": time_module.time(),
        }

        topic = self._settings.kafka.topic_memory_result

        try:
            await asyncio.wait_for(
                self._producer.send(topic=topic, key=user_id, value=message),
                timeout=5.0,
            )
            return True
        except Exception as e:
            logger.error(f"Kafka 结果发布失败: {e}")
            return False

    async def publish_to_dlq(
        self,
        request_id: str,
        user_id: str,
        body_dict: dict,
        error: str,
        retries: int,
    ) -> bool:
        """投递失败消息到死信队列"""
        if not self.is_available:
            return False

        message = {
            "request_id": request_id,
            "user_id": user_id,
            "body": body_dict,
            "error": error,
            "retries_attempted": retries,
            "timestamp": time_module.time(),
        }

        topic = self._settings.kafka.topic_memory_dlq

        try:
            await asyncio.wait_for(
                self._producer.send(topic=topic, key=user_id, value=message),
                timeout=5.0,
            )
            logger.info(f"消息已投递 DLQ: request_id={request_id}, retries={retries}")
            return True
        except Exception as e:
            logger.error(f"DLQ 投递失败: {e}")
            return False


# 全局单例
mq_producer = MQProducer()
