"""Agent 调工具的统一入口。

架构图里 Agent -> MCP Server 是独立一跳。这里支持两种模式：

* ``mcp``   —— 走真实 MCP（streamable HTTP，``http://host:port/mcp``）
* ``local`` —— 进程内直接调用同一个函数

MCP 调用失败会自动降级到 local，并打一条 warning，
所以即使某个 MCP Server 没起来，整条链路也不会断。
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Callable

from zhixue.config import get_settings
from zhixue.logging_setup import get_logger
from zhixue.registry import AGENT_TO_MCP, mcp_url
from zhixue.tools import analysis_tools, docgen_tools, grading_tools, question_tools

logger = get_logger("tool_client")

#: 每个 MCP Server 暴露的工具 -> 本地实现
LOCAL_TOOLS: dict[str, dict[str, Callable[..., Any]]] = {
    "docgen": {
        "search_textbook": docgen_tools.search_textbook,
        "list_templates": docgen_tools.list_templates,
        "render_word": docgen_tools.render_word,
        "build_study_plan": docgen_tools.build_study_plan,
        "build_lecture_note": docgen_tools.build_lecture_note,
    },
    "question": {
        "list_knowledge_points": question_tools.list_knowledge_points,
        "resolve_knowledge_point": question_tools.resolve_knowledge_point,
        "search_question_bank": question_tools.search_question_bank,
        "select_questions": question_tools.select_questions,
        "create_homework": question_tools.create_homework,
        "build_exam_from_ids": question_tools.build_exam_from_ids,
    },
    "grading": {
        "ocr_extract": grading_tools.ocr_extract,
        "compare_answer": grading_tools.compare_answer,
        "get_homework": grading_tools.get_homework,
        "list_student_answers": grading_tools.list_student_answers,
        "grade_submission": grading_tools.grade_submission,
        "sync_mistake_records": grading_tools.sync_mistake_records,
    },
    "analysis": {
        "text_to_sql": analysis_tools.text_to_sql,
        "run_sql": analysis_tools.run_sql,
        "student_profile": analysis_tools.student_profile,
        "weak_knowledge_points": analysis_tools.weak_knowledge_points,
        "score_trend": analysis_tools.score_trend,
        "class_comparison": analysis_tools.class_comparison,
        "frequent_mistakes": analysis_tools.frequent_mistakes,
        "write_mistake_records": analysis_tools.write_mistake_records,
    },
}


# --------------------------------------------------------------------------- #
# 后台事件循环：让同步代码也能安全地 await 异步客户端
# --------------------------------------------------------------------------- #
_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            _loop_thread = threading.Thread(
                target=_loop.run_forever, name="zhixue-async", daemon=True
            )
            _loop_thread.start()
        return _loop


def run_async(coro: Any, timeout: float = 180.0) -> Any:
    """在后台事件循环里跑一个协程并等结果。"""
    future = asyncio.run_coroutine_threadsafe(coro, _get_loop())
    return future.result(timeout=timeout)


class ToolClient:
    """某个 Agent 访问自己那台 MCP Server 的客户端。"""

    def __init__(self, agent: str, transport: str | None = None) -> None:
        self.agent = agent
        self.settings = get_settings()
        self.transport = transport or self.settings.tool_transport

    @property
    def mcp_server(self) -> str:
        return AGENT_TO_MCP.get(self.agent, self.agent)

    @property
    def url(self) -> str:
        return mcp_url(self.agent)

    # -- 对外 API ---------------------------------------------------------- #
    def call(self, tool: str, **arguments: Any) -> Any:
        """同步调用一个工具（Agent 的 handler 都是同步的）。"""
        if self.transport == "mcp":
            try:
                return run_async(self._call_mcp(tool, arguments))
            except Exception as exc:  # noqa: BLE001 - MCP 不可用就降级
                logger.warning("MCP 调用 %s.%s 失败(%s)，降级为本地调用", self.agent, tool, exc)
        return self.call_local(tool, **arguments)

    def call_local(self, tool: str, **arguments: Any) -> Any:
        table = LOCAL_TOOLS.get(self.agent, {})
        if tool not in table:
            raise KeyError(f"{self.agent} 没有名为 {tool} 的工具")
        return table[tool](**arguments)

    # -- MCP --------------------------------------------------------------- #
    async def _call_mcp(self, tool: str, arguments: dict[str, Any]) -> Any:
        from fastmcp import Client

        async with Client(self.url) as client:
            result = await client.call_tool(tool, arguments)
        return _unwrap(result)


def _unwrap(result: Any) -> Any:
    """把 MCP 的返回结果还原成 Python 对象。"""
    for attr in ("data", "structured_content", "structuredContent"):
        value = getattr(result, attr, None)
        if value is not None:
            return value
    content = getattr(result, "content", None)
    if isinstance(content, list) and content:
        texts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text is None and isinstance(item, dict):
                text = item.get("text")
            if text:
                texts.append(str(text))
        if texts:
            raw = texts[0] if len(texts) == 1 else "\n".join(texts)
            try:
                return json.loads(raw)
            except ValueError:
                return raw
    if isinstance(result, (dict, list, str, int, float, bool)) or result is None:
        return result
    return str(result)


__all__ = ["ToolClient", "LOCAL_TOOLS", "run_async"]
