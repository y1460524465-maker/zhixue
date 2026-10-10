"""A2AClient：把任务派发给别的 Agent。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from zhixue.config import get_settings
from zhixue.logging_setup import get_logger, set_task_id
from zhixue.schemas import TaskRequest, TaskResult

logger = get_logger("a2a.client")


class A2AClient:
    """按 A2A 协议（或等价 HTTP 兜底）调用远端 Agent。"""

    def __init__(self, transport: str | None = None, timeout: float = 180.0) -> None:
        self.settings = get_settings()
        self.transport = transport or self.settings.network_transport
        self.timeout = timeout
        self._sdk_available: bool | None = None

    # -- 能力探测 ---------------------------------------------------------- #
    @property
    def sdk_available(self) -> bool:
        if self._sdk_available is None:
            try:
                import a2a.client  # noqa: F401

                self._sdk_available = True
            except ImportError:
                self._sdk_available = False
                logger.warning("未安装 a2a-sdk，主应用将使用 POST /task/send 兜底协议")
        return self._sdk_available

    @property
    def use_sdk(self) -> bool:
        return self.transport == "a2a" and self.sdk_available

    # -- 单个任务 ---------------------------------------------------------- #
    async def send(self, agent: str, request: TaskRequest) -> TaskResult:
        set_task_id(request.task_id)
        url = self.settings.url(agent)
        logger.info("派发任务 -> %s (%s) intent=%s", agent, url, request.intent)
        if self.use_sdk:
            try:
                return await self._send_via_sdk(url, request)
            except Exception as exc:  # noqa: BLE001 - SDK 出问题就退回兜底协议
                logger.warning("A2A SDK 调用失败(%s)，改用 POST /task/send", exc)
        return await self._send_via_http(url, request)

    async def _send_via_http(self, url: str, request: TaskRequest) -> TaskResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{url}/task/send", json=request.model_dump())
            response.raise_for_status()
            return TaskResult.model_validate(response.json())

    async def _send_via_sdk(self, url: str, request: TaskRequest) -> TaskResult:
        from a2a.client import ClientConfig, create_client
        from a2a.helpers.proto_helpers import new_text_message
        from a2a.types import Role, SendMessageRequest

        # 默认 httpx 超时只有几秒，Agent 里要跑检索/LLM，必须显式放宽
        http_client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout))
        try:
            client = await create_client(
                url, client_config=ClientConfig(httpx_client=http_client, streaming=False)
            )
            try:
                message = new_text_message(request.model_dump_json(), role=Role.ROLE_USER)
                texts: list[str] = []
                async for event in client.send_message(SendMessageRequest(message=message)):
                    text = extract_text(event)
                    if text:
                        texts.append(text)
                if not texts:
                    raise RuntimeError("A2A 未返回任何内容")
                return TaskResult.model_validate(json.loads(texts[-1]))
            finally:
                close = getattr(client, "close", None)
                if close is not None:
                    await close()
        finally:
            await http_client.aclose()

    # -- 并发派发 ---------------------------------------------------------- #
    async def send_many(self, jobs: list[tuple[str, TaskRequest]]) -> list[TaskResult]:
        """并发派发给多个 Agent（一句话包含多个意图时用）。"""
        return list(await asyncio.gather(*(self.send(agent, req) for agent, req in jobs)))


def extract_text(event: Any) -> str:
    """从 A2A 的 StreamResponse 里取出文本。"""
    try:
        from a2a.helpers.proto_helpers import get_message_text, get_stream_response_text

        text = get_stream_response_text(event)
        if text:
            return text
        message = getattr(event, "message", None)
        if message is not None and message.WhichOneof("payload") is not None:
            return get_message_text(message)
    except Exception:  # noqa: BLE001 - 兼容不同版本的返回结构
        pass
    if isinstance(event, dict):
        return str(event.get("text", ""))
    return ""


__all__ = ["A2AClient", "extract_text"]
