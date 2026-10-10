"""结果优化：把多个 Agent 的结果合成一段人话 + 前端要的卡片。"""

from __future__ import annotations

from typing import Any

from zhixue.config import get_settings
from zhixue.llm import LLMError, get_llm
from zhixue.logging_setup import get_logger
from zhixue.registry import AGENT_DISPLAY_NAME
from zhixue.schemas import ChatResponse, Intent, RouterDecision, TaskResult

logger = get_logger("app.summarizer")


def card_for(result: TaskResult) -> dict[str, Any] | None:
    """把 Agent 的结构化数据转成前端卡片。"""
    data = result.data or {}
    if result.intent is Intent.GRADING:
        return {
            "type": "grading",
            "title": "批改结果",
            "score": data.get("score"),
            "full_score": data.get("full_score"),
            "rate": data.get("rate"),
            "items": [
                {
                    "stem": str(d.get("stem", ""))[:70],
                    "student_answer": d.get("student_answer", ""),
                    "std_answer": d.get("std_answer", ""),
                    "score": d.get("score"),
                    "full_score": d.get("full_score"),
                    "is_correct": d.get("is_correct"),
                    "comment": d.get("comment"),
                }
                for d in (data.get("details") or [])
            ],
            "kp_scores": data.get("kp_scores") or {},
        }
    if result.intent is Intent.ANALYSIS:
        if data.get("overview") is None:
            return {
                "type": "info",
                "title": "错题同步",
                "text": f"已同步错题 {data.get('mistakes', 0)} 条",
            }
        return {
            "type": "analysis",
            "title": "学情画像",
            "student": data.get("student") or {},
            "overview": data.get("overview") or {},
            "weak_points": data.get("weak_points") or [],
            "trend": data.get("trend") or [],
            "comparison": data.get("comparison") or {},
            "mistakes": data.get("top_mistakes") or [],
        }
    if result.intent is Intent.QUESTION_GEN:
        return {
            "type": "questions",
            "title": "试题清单",
            "source": data.get("source"),
            "student_id": data.get("student_id"),
            "mistake_count": data.get("mistake_count"),
            "reused": data.get("reused"),
            "knowledge_point": data.get("knowledge_point"),
            "homework": data.get("homework"),
            "document": data.get("document"),
            "similar": data.get("similar") or [],
            "questions": [
                {
                    "q_id": q.get("q_id"),
                    "q_type": q.get("q_type"),
                    "difficulty": q.get("difficulty"),
                    "stem": q.get("stem"),
                    "options": q.get("options"),
                    "answer": q.get("answer"),
                    "analysis": q.get("analysis"),
                }
                for q in (data.get("questions") or [])
            ],
        }
    if result.intent is Intent.DOC_GEN:
        return {
            "type": "document",
            "title": "生成文档",
            "topic": data.get("topic"),
            "content": data.get("content") or {},
            "references": data.get("references") or [],
            "files": result.artifacts,
        }
    return None


def build_cards(results: list[TaskResult]) -> list[dict[str, Any]]:
    return [c for c in (card_for(r) for r in results) if c]


class ResultSummarizer:
    """架构图最下面那个"结果优化 - LLM 总结"。"""

    def __init__(self) -> None:
        self.settings = get_settings()

    def summarize(self, decision: RouterDecision, results: list[TaskResult]) -> str:
        if not results:
            return "这次没有匹配到可以处理的任务，换个说法再试一次吧。"
        if len(results) == 1:
            return results[0].text or "处理完成。"

        blocks = "\n\n".join(
            f"【{AGENT_DISPLAY_NAME.get(r.agent, r.agent)}】\n{r.text}" for r in results
        )
        prompt = (
            "下面是多个教学 Agent 对同一请求的处理结果，请合并成一段连贯的答复，"
            "保留关键数据（分数、知识点、文件名），不要重复，300 字以内。\n\n"
            f"{blocks}"
        )
        try:
            return get_llm().chat(prompt)
        except LLMError as exc:
            logger.warning("汇总 LLM 不可用(%s)，改为直接拼接", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("汇总异常(%s)，改为直接拼接", exc)
        return blocks

    def build_response(
        self,
        session_id: str,
        decision: RouterDecision,
        results: list[TaskResult],
        elapsed: float,
    ) -> ChatResponse:
        text = self.summarize(decision, results)
        failed = bool(results) and all(r.status == "error" for r in results)
        return ChatResponse(
            session_id=session_id,
            type="error" if failed else "answer",
            text=text,
            intent=decision.intent,
            slots=decision.slots,
            missing=[],
            cards=build_cards(results),
            agents=[r.agent for r in results],
            elapsed=elapsed,
        )


__all__ = ["ResultSummarizer", "card_for", "build_cards"]
