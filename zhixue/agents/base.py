"""Agent 通用骨架：读取槽位 -> 调 MCP 工具 -> LLM 组织语言 -> 返回 TaskResult。"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from zhixue.a2a.server import AgentService, AgentSpec
from zhixue.config import get_settings
from zhixue.llm import LLMError, get_llm
from zhixue.logging_setup import get_logger, set_task_id
from zhixue.schemas import Intent, TaskRequest, TaskResult
from zhixue.tool_client import ToolClient


class BaseAgent(ABC):
    """所有 Agent 的公共逻辑。"""

    key: str = ""
    name: str = ""
    description: str = ""
    instructions: str = ""
    intent: Intent = Intent.TEXTBOOK_QA

    def __init__(self, transport: str | None = None) -> None:
        self.settings = get_settings()
        self.logger = get_logger(f"agent.{self.key}")
        self.tools = ToolClient(self.key, transport)

    # ------------------------------------------------------------------ #
    # 子类实现
    # ------------------------------------------------------------------ #
    @abstractmethod
    def run(self, request: TaskRequest) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        """返回 ``(给用户看的文字, 结构化数据, 附件列表)``。"""

    # ------------------------------------------------------------------ #
    # 框架
    # ------------------------------------------------------------------ #
    @property
    def port(self) -> int:
        return self.settings.ports.port(self.key)

    def spec(self) -> AgentSpec:
        return AgentSpec(
            key=self.key,
            name=self.name,
            description=self.description,
            port=self.port,
            handler=self.handle,
            instructions=self.instructions,
        )

    def handle(self, request: TaskRequest) -> TaskResult:
        """AgentService 调用的入口，负责计时与异常兜底。"""
        set_task_id(request.task_id)
        started = time.time()
        try:
            text, data, artifacts = self.run(request)
            status = "ok"
            error = None
        except Exception as exc:  # noqa: BLE001 - 单个 Agent 失败不应该炸掉整条链路
            self.logger.exception("[%s] 执行失败", self.key)
            text = f"{self.name}处理失败：{exc}"
            data = {}
            artifacts = []
            status = "error"
            error = str(exc)
        return TaskResult(
            task_id=request.task_id,
            agent=self.key,
            intent=request.intent,
            status=status,
            text=text,
            data=data,
            artifacts=artifacts,
            elapsed=round(time.time() - started, 2),
            error=error,
        )

    def serve(self) -> None:
        AgentService(self.spec()).run()

    # ------------------------------------------------------------------ #
    # 便捷方法
    # ------------------------------------------------------------------ #
    def slot(self, request: TaskRequest, name: str, default: Any = None) -> Any:
        value = request.slots.get(name)
        if value in (None, ""):
            return default
        return value

    def slot_text(self, request: TaskRequest) -> str:
        for key in ("raw_input", "question", "text", "query"):
            value = request.slots.get(key)
            if value:
                return str(value)
        return ""

    def chat(self, prompt: str, system: str | None = None, fallback: str = "") -> str:
        """调 LLM；失败不影响主流程（返回 fallback）。"""
        try:
            llm = get_llm()
            return llm.chat(prompt, system=system or self.system_prompt())
        except LLMError as exc:
            self.logger.warning("[%s] LLM 不可用(%s)，使用规则化输出", self.key, exc)
            return fallback
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("[%s] LLM 调用异常(%s)，使用规则化输出", self.key, exc)
            return fallback

    def chat_json(
        self, prompt: str, fallback: dict[str, Any] | None = None, system: str | None = None
    ) -> dict[str, Any]:
        """要模型输出 JSON；失败返回 fallback，保证 Agent 永远有结果。"""
        fallback = fallback if fallback is not None else {}
        try:
            llm = get_llm()
            return llm.chat_json(
                prompt, system=system or self.system_prompt(), fallback=fallback
            )
        except LLMError as exc:
            self.logger.warning("[%s] LLM(JSON) 不可用(%s)，使用兜底数据", self.key, exc)
            return fallback
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("[%s] LLM(JSON) 异常(%s)，使用兜底数据", self.key, exc)
            return fallback

    def system_prompt(self) -> str:
        return (
            f"你是「智学」智慧教学系统中的{self.name}。"
            f"{self.instructions}"
            "回答面向学生，语气专业、简洁，使用中文。"
        )


__all__ = ["BaseAgent"]
