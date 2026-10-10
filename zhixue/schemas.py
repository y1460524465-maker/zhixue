"""智学的数据契约。

三个关键结构贯穿全链路：

* :class:`RouterDecision` —— LLM Router 的输出（意图 + 槽位 + 是否缺信息）
* :class:`TaskRequest` —— 主应用经 AgentNetwork/A2A 下发给 Agent 的任务
* :class:`TaskResult` —— Agent 回给主应用的结果

它们同时也是 Pydantic 模型，可以直接 ``model_dump_json()`` 走 HTTP。
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Intent(str, Enum):
    """架构图里 LLM Router 能识别出的意图。"""

    DOC_GEN = "doc_gen"            # 文档生成 Agent
    QUESTION_GEN = "question_gen"  # 出题 Agent
    GRADING = "grading"            # 作业批改 Agent
    ANALYSIS = "analysis"          # 学情分析 Agent
    TEXTBOOK_QA = "textbook_qa"    # 课本知识问答（走 RAG）
    CHITCHAT = "chitchat"          # 闲聊/问候


INTENT_LABELS: dict[Intent, str] = {
    Intent.DOC_GEN: "文档生成",
    Intent.QUESTION_GEN: "试题生成",
    Intent.GRADING: "作业批改",
    Intent.ANALYSIS: "学情分析",
    Intent.TEXTBOOK_QA: "课本答疑",
    Intent.CHITCHAT: "闲聊问候",
}

#: 每个意图必须凑齐的槽位，缺一个就回去问用户
REQUIRED_SLOTS: dict[Intent, tuple[str, ...]] = {
    Intent.DOC_GEN: ("topic",),
    Intent.QUESTION_GEN: ("knowledge_point",),
    Intent.GRADING: ("student_id", "homework_id"),
    Intent.ANALYSIS: ("student_id",),
    Intent.TEXTBOOK_QA: ("question",),
    Intent.CHITCHAT: (),
}

#: 出题时出现这些词，说明用户想练"错过的题"（样本式入口），而不是按知识点出题
MISTAKE_HINTS: tuple[str, ...] = (
    "错题", "做错", "错的题", "错过的", "不会的题", "做不对",
    "薄弱", "不熟", "没掌握", "再练一遍", "重新做", "巩固",
)


def wants_mistakes(text: str) -> bool:
    """判断一段话是不是在说"给我出错过的题"。"""
    return any(hint in (text or "") for hint in MISTAKE_HINTS)


class RouterDecision(BaseModel):
    """LLM Router 的判定结果。"""

    intent: Intent
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    slots: dict[str, Any] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    reply: str = ""
    matched_intents: list[Intent] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing


class TaskRequest(BaseModel):
    """主应用 -> Agent 的任务包（也是 A2A message 的 payload）。"""

    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str = ""
    #: 账号身份。入口解析一次，之后随任务包一路传递，任何一层都不重新解析。
    user_id: str = ""
    intent: Intent
    slots: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, str]] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)


class TaskResult(BaseModel):
    """Agent -> 主应用的结果包。"""

    task_id: str
    agent: str
    intent: Intent
    status: Literal["ok", "partial", "error"] = "ok"
    text: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    elapsed: float = 0.0
    error: str | None = None


class ChatRequest(BaseModel):
    """前端 -> 主应用。"""

    message: str
    session_id: str | None = None
    student_id: str | None = None
    upload_paths: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """主应用 -> 前端。"""

    session_id: str
    type: Literal["ask_user", "answer", "error"]
    text: str
    intent: Intent | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    cards: list[dict[str, Any]] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    elapsed: float = 0.0


__all__ = [
    "Intent",
    "INTENT_LABELS",
    "REQUIRED_SLOTS",
    "MISTAKE_HINTS",
    "wants_mistakes",
    "RouterDecision",
    "TaskRequest",
    "TaskResult",
    "ChatRequest",
    "ChatResponse",
]
