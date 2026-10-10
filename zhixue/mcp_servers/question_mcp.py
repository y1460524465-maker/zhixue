"""MCP Question —— 出题工具服务（:8011/mcp）。

对应架构图的 ``RAG 题库检索`` -> ``题目向量库``，
以及"选题 -> 组卷 -> 落成作业"这条出题链路。
"""

from __future__ import annotations

from typing import Any

from zhixue.config import get_settings
from zhixue.mcp_servers._runner import serve
from zhixue.tools import question_tools

NAME = "智学 MCP Question"
INSTRUCTIONS = (
    "提供题库检索、知识点解析、结构化选题、组卷与作业下发能力。"
    "出题标准流程：resolve_knowledge_point -> select_questions -> "
    "create_homework / build_exam_from_ids。"
)


def register(mcp: Any) -> None:
    @mcp.tool
    def list_knowledge_points(subject: str | None = None) -> list[dict[str, Any]]:
        """列出知识点（可按学科过滤）。"""
        return question_tools.list_knowledge_points(subject=subject)

    @mcp.tool
    def resolve_knowledge_point(knowledge_point: str, subject: str | None = None) -> dict[str, Any] | None:
        """把自由文本（如"装饰器"）解析成知识点记录，返回 None 表示没匹配上。"""
        return question_tools.resolve_knowledge_point(knowledge_point, subject=subject)

    @mcp.tool
    def search_question_bank(query: str, subject: str | None = None, k: int = 5) -> list[dict[str, Any]]:
        """在题目向量库里做语义检索。"""
        return question_tools.search_question_bank(query, subject=subject, k=k)

    @mcp.tool
    def select_questions(
        kp_id: str | None = None,
        subject: str | None = None,
        q_type: str | None = None,
        difficulty: int | None = None,
        n: int = 5,
        shuffle: bool = False,
    ) -> list[dict[str, Any]]:
        """按知识点/题型/难度筛选题目。q_type 取值：单选/多选/判断/填空/简答。"""
        return question_tools.select_questions(
            kp_id=kp_id, subject=subject, q_type=q_type,
            difficulty=difficulty, n=n, shuffle=shuffle,
        )

    @mcp.tool
    def create_homework(
        title: str,
        question_ids: list[str],
        subject: str | None = None,
        kp_id: str | None = None,
        score_per_question: int = 20,
    ) -> dict[str, Any]:
        """把选中的题目落成一份正式作业（写入作业库与作业答案库）。"""
        return question_tools.create_homework(
            title, question_ids, subject=subject, kp_id=kp_id,
            score_per_question=score_per_question,
        )

    @mcp.tool
    def build_exam_from_ids(
        title: str, question_ids: list[str], subject: str = "", duration: int = 60
    ) -> dict[str, Any]:
        """按题号生成一份试卷 Word 文档。"""
        return question_tools.build_exam_from_ids(
            title, question_ids, subject=subject, duration=duration
        )

    @mcp.tool
    def get_questions_by_ids(question_ids: list[str]) -> list[dict[str, Any]]:
        """按题目编号批量取题（错题记录里只有编号，题干要回题库换）。"""
        return question_tools.get_questions_by_ids(question_ids)

    @mcp.tool
    def record_issued_questions(
        student_id: str,
        question_ids: list[str],
        homework_id: str | None = None,
        source: str = "homework",
    ) -> int:
        """记录"这些题发给过这个学生"，供下次出题时排除重复。"""
        return question_tools.record_issued_questions(
            student_id, question_ids, homework_id=homework_id, source=source
        )

    @mcp.tool
    def recently_issued_q_ids(student_id: str, days: int = 30) -> list[str]:
        """最近若干天已经发给这个学生的题目编号。"""
        return question_tools.recently_issued_q_ids(student_id, days=days)


def main() -> None:
    serve(
        service="MCP Question",
        name=NAME,
        instructions=INSTRUCTIONS,
        register=register,
        default_port=get_settings().ports.question_mcp,
    )


if __name__ == "__main__":
    main()
