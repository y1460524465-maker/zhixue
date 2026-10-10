"""课本答疑：RAG 检索 + LLM 归纳。

架构图上没有单独的"答疑 Agent"，这条链路属于主应用：

    用户提问 -> RAG 课本检索（课本向量库）-> LLM 带着资料作答 -> 用户界面展示
"""

from __future__ import annotations

from typing import Any

from zhixue.llm import LLMError, get_llm
from zhixue.logging_setup import get_logger
from zhixue.tools.docgen_tools import search_textbook

logger = get_logger("app.qa")

QA_SYSTEM = (
    "你是「智学」的课本答疑老师。只依据给定的课本资料回答，"
    "资料没提到的内容不要编造；回答分点、口语化、控制在 250 字以内。"
)


def answer_question(
    query: str, subject: str | None = None, k: int = 4
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """返回 ``(回答文本, 结构化数据, 引用片段)``。"""
    chunks = search_textbook(query, subject=subject, k=k)
    references = [
        {
            "title": c.get("title", ""),
            "chapter": c.get("chapter", ""),
            "score": c.get("score", 0),
            "backend": c.get("backend", ""),
            "content": (c.get("content") or "")[:160],
        }
        for c in chunks
    ]
    context = "\n\n".join(
        f"[{i + 1}] {c.get('title', '')}\n{c.get('content', '')}"
        for i, c in enumerate(chunks)
    ) or "（课本库暂无相关内容）"

    prompt = (
        f"课本资料：\n{context}\n\n"
        f"学生问题：{query}\n\n"
        "请给出回答，并在末尾用「参考：[编号]」标注用到的资料。"
    )
    try:
        text = get_llm().chat(prompt, system=QA_SYSTEM)
    except LLMError as exc:
        logger.warning("答疑 LLM 不可用(%s)，直接返回课本原文", exc)
        text = _fallback(query, chunks)
    except Exception as exc:  # noqa: BLE001
        logger.warning("答疑异常(%s)，直接返回课本原文", exc)
        text = _fallback(query, chunks)

    data = {
        "question": query,
        "subject": subject,
        "references": references,
        "retrieval_backend": chunks[0].get("backend", "-") if chunks else "-",
    }
    return text, data, references


def _fallback(query: str, chunks: list[dict[str, Any]]) -> str:
    if not chunks:
        return f"课本库里暂时没有检索到与「{query}」直接相关的资料，换个关键词再试试？"
    parts = [f"关于「{query}」，课本上的相关表述是："]
    for index, chunk in enumerate(chunks[:2], start=1):
        parts.append(f"\n[{index}] {chunk.get('title', '')}\n{chunk.get('content', '')}")
    return "\n".join(parts)


__all__ = ["answer_question"]
