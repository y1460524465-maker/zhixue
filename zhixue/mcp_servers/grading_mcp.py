"""MCP Grading —— 作业批改工具服务（:8012/mcp）。

对应架构图的 ``OCR 识别`` + ``答案比对`` -> ``作业答案库``。
"""

from __future__ import annotations

from typing import Any

from zhixue.config import get_settings
from zhixue.mcp_servers._runner import serve
from zhixue.tools import grading_tools

NAME = "智学 MCP Grading"
INSTRUCTIONS = (
    "提供答题卡 OCR 识别、答案比对与整份作业批改能力。"
    "标准流程：get_homework 拿到标准答案 -> ocr_extract 识别作答 -> "
    "grade_submission 完成批改并落库。"
)


def register(mcp: Any) -> None:
    @mcp.tool
    def ocr_extract(file_path: str) -> dict[str, Any]:
        """识别答题卡图片，返回原文行与 {题号: 作答}。"""
        return grading_tools.ocr_extract(file_path)

    @mcp.tool
    def compare_answer(
        student_answer: str,
        std_answer: str,
        q_type: str = "简答",
        stem: str = "",
        rubric: str = "",
        use_llm: bool = True,
    ) -> dict[str, Any]:
        """比对一道题：客观题规则匹配，主观题走 LLM 评分（失败自动降级关键词覆盖）。"""
        return grading_tools.compare_answer(
            student_answer, std_answer, q_type=q_type, stem=stem, rubric=rubric, use_llm=use_llm
        )

    @mcp.tool
    def get_homework(homework_id: str) -> dict[str, Any]:
        """取作业信息与题目标准答案。"""
        return grading_tools.get_homework(homework_id)

    @mcp.tool
    def list_student_answers(
        homework_id: str, student_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """读取某学生某次作业已有的逐题作答记录（用于重新批改）。"""
        return grading_tools.list_student_answers(homework_id, student_id, limit=limit)

    @mcp.tool
    def grade_submission(
        homework_id: str,
        student_id: str,
        file_path: str | None = None,
        student_answers: dict[str, str] | None = None,
        use_llm: bool = True,
    ) -> dict[str, Any]:
        """批改一次作业并落库，返回总分、得分率、逐题明细。"""
        return grading_tools.grade_submission(
            homework_id, student_id, file_path=file_path,
            student_answers=student_answers, use_llm=use_llm,
        )

    @mcp.tool
    def sync_mistake_records(student_id: str, homework_id: str | None = None) -> dict[str, Any]:
        """把批改出的错题同步进错题记录库。"""
        return grading_tools.sync_mistake_records(student_id, homework_id)


def main() -> None:
    serve(
        service="MCP Grading",
        name=NAME,
        instructions=INSTRUCTIONS,
        register=register,
        default_port=get_settings().ports.grading_mcp,
    )


if __name__ == "__main__":
    main()
