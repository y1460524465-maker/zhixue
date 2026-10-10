"""把业务 handler 暴露成一个 A2A Agent 服务。"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import FastAPI, HTTPException

from zhixue.a2a.cards import build_sdk_card, card_dict
from zhixue.config import get_settings
from zhixue.logging_setup import get_logger, set_task_id
from zhixue.schemas import Intent, TaskRequest, TaskResult

logger = get_logger("a2a.server")

# Agent 的业务处理函数签名：TaskRequest -> TaskResult
TaskHandler = Callable[[TaskRequest], TaskResult]


@dataclass
class AgentSpec:
    """描述一个 Agent 的最小信息。"""

    key: str  # docgen / question / grading / analysis
    name: str
    description: str
    port: int
    handler: TaskHandler
    instructions: str = ""
    extra_routes: list[str] = field(default_factory=list)


class AgentService:
    """一个 A2A Agent 的完整 HTTP 服务。"""

    def __init__(self, spec: AgentSpec) -> None:
        self.spec = spec
        self.settings = get_settings()
        self.url = f"http://{self.settings.host}:{spec.port}"
        self.sdk_ready = False

    # -- 业务入口 ---------------------------------------------------------- #
    def _invoke(self, payload: TaskRequest) -> TaskResult:
        set_task_id(payload.task_id)
        logger.info("[%s] 收到任务 intent=%s slots=%s", self.spec.key, payload.intent, payload.slots)
        try:
            result = self.spec.handler(payload)
        except Exception as exc:  # noqa: BLE001 - 兜住业务异常，转成 error 结果
            logger.exception("[%s] 处理失败", self.spec.key)
            return TaskResult(
                task_id=payload.task_id,
                agent=self.spec.key,
                intent=payload.intent,
                status="error",
                text=f"处理失败：{exc}",
                error=str(exc),
            )
        logger.info(
            "[%s] 完成 status=%s elapsed=%.2fs", self.spec.key, result.status, result.elapsed
        )
        return result

    async def _invoke_async(self, payload: TaskRequest) -> TaskResult:
        return await asyncio.get_running_loop().run_in_executor(None, self._invoke, payload)

    # -- 路由 -------------------------------------------------------------- #
    def build(self) -> FastAPI:
        spec = self.spec
        app = FastAPI(
            title=f"智学 {spec.name}", description=spec.description, version="1.0.0"
        )

        @app.get("/health")
        async def health() -> dict[str, Any]:
            return {
                "status": "healthy",
                "agent": spec.key,
                "name": spec.name,
                "a2a": self.sdk_ready,
                "url": self.url,
            }

        @app.get("/skills")
        async def skills() -> dict[str, Any]:
            card = card_dict(spec.key, spec.name, spec.description, self.url)
            return {"agent": spec.key, "skills": card["skills"]}

        @app.get("/.well-known/agent-card.json")
        async def agent_card() -> dict[str, Any]:
            return card_dict(spec.key, spec.name, spec.description, self.url)

        @app.post("/task/send")
        async def task_send(payload: dict[str, Any]) -> dict[str, Any]:
            """架构图上的 ``POST /task/send``。

            既接受完整 TaskRequest，也接受 ``{"text": "..."}`` 这种简写。
            """
            try:
                request = coerce_request(payload, spec.key)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=400, detail=f"任务格式不合法: {exc}") from exc
            result = await self._invoke_async(request)
            return result.model_dump()

        @app.get("/agent/info")
        async def agent_info() -> dict[str, Any]:
            return {
                "agent": spec.key,
                "name": spec.name,
                "description": spec.description,
                "instructions": spec.instructions,
                "url": self.url,
                "port": spec.port,
                "a2a_sdk": self.sdk_ready,
            }

        self._mount_a2a(app)
        return app

    def _mount_a2a(self, app: FastAPI) -> None:
        """挂上标准 A2A 路由；SDK 不可用时跳过，仅保留兜底接口。"""
        try:
            from a2a.helpers.proto_helpers import new_text_message
            from a2a.server.agent_execution import AgentExecutor, RequestContext
            from a2a.server.request_handlers import DefaultRequestHandler
            from a2a.server.routes import (
                add_a2a_routes_to_fastapi,
                create_agent_card_routes,
                create_jsonrpc_routes,
                create_rest_routes,
            )
            from a2a.server.tasks import InMemoryTaskStore
            from a2a.types import Role
        except ImportError as exc:
            logger.warning(
                "未安装 a2a-sdk(%s)：%s 仅提供 POST /task/send 兜底接口", exc, self.spec.key
            )
            return

        service = self

        class _Executor(AgentExecutor):
            """把 A2A message 转成 TaskRequest，再把 TaskResult 转回 message。"""

            async def execute(self, context: RequestContext, event_queue) -> None:  # noqa: ANN001
                text = context.get_user_input()
                task_id = context.task_id or uuid.uuid4().hex
                context_id = context.context_id or uuid.uuid4().hex
                request = request_from_text(text, service.spec.key, task_id)
                result = await service._invoke_async(request)
                await event_queue.enqueue_event(
                    new_text_message(
                        result.model_dump_json(),
                        context_id=context_id,
                        task_id=task_id,
                        role=Role.ROLE_AGENT,
                    )
                )

            async def cancel(self, context: RequestContext, event_queue) -> None:  # noqa: ANN001
                logger.info("[%s] 收到取消请求 task=%s", service.spec.key, context.task_id)

        card = build_sdk_card(self.spec.key, self.spec.name, self.spec.description, self.url)
        if card is None:
            return
        try:
            handler = DefaultRequestHandler(
                agent_executor=_Executor(),
                task_store=InMemoryTaskStore(),
                agent_card=card,
            )
            add_a2a_routes_to_fastapi(
                app,
                agent_card_routes=create_agent_card_routes(card),
                jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/"),
                rest_routes=create_rest_routes(handler),
            )
            self.sdk_ready = True
            logger.info("[%s] 已挂载标准 A2A 路由（JSON-RPC message/send）", self.spec.key)
        except Exception as exc:  # noqa: BLE001 - 兼容性问题不应影响兜底接口
            logger.warning("[%s] 挂载 A2A 路由失败: %s", self.spec.key, exc)

    # -- 启动 -------------------------------------------------------------- #
    def run(self) -> None:
        import uvicorn

        app = self.build()  # 先构建，日志里就能看到 A2A 是否就绪
        logger.info(
            "启动 %s -> http://%s:%d （A2A SDK: %s）",
            self.spec.name,
            self.settings.host,
            self.spec.port,
            "已启用" if self.sdk_ready else "未启用",
        )
        uvicorn.run(app, host=self.settings.host, port=self.spec.port, log_level="info")


# --------------------------------------------------------------------------- #
# 入参兼容
# --------------------------------------------------------------------------- #
INTENT_BY_AGENT: dict[str, Intent] = {
    "docgen": Intent.DOC_GEN,
    "question": Intent.QUESTION_GEN,
    "grading": Intent.GRADING,
    "analysis": Intent.ANALYSIS,
}


def coerce_request(payload: dict[str, Any], agent: str) -> TaskRequest:
    """接受完整 TaskRequest，也接受 ``{"text": "..."}`` 简写。"""
    if "intent" in payload:
        return TaskRequest.model_validate(payload)
    text = payload.get("text") or payload.get("message") or json.dumps(payload, ensure_ascii=False)
    return request_from_text(text, agent, uuid.uuid4().hex)


def request_from_text(text: str, agent: str, task_id: str) -> TaskRequest:
    """把 A2A message 的文本还原成 TaskRequest。"""
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "intent" in data:
            request = TaskRequest.model_validate(data)
            if not request.task_id:
                request.task_id = task_id
            return request
    except (TypeError, ValueError):
        pass

    return TaskRequest(
        task_id=task_id,
        intent=INTENT_BY_AGENT.get(agent, Intent.TEXTBOOK_QA),
        slots={"raw_input": text},
    )


__all__ = ["AgentService", "AgentSpec", "TaskHandler", "coerce_request", "request_from_text"]
