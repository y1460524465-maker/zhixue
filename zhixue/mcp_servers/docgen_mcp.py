"""MCP DocGen —— 文档生成工具服务（:8010/mcp）。

对应架构图右下角的 ``RAG 课本检索`` 与 ``Word 模板生成``，
分别落到 ``课本向量库`` 和 ``Word 模板库``。
"""

from __future__ import annotations

from typing import Any

from zhixue.config import get_settings
from zhixue.mcp_servers._runner import serve
from zhixue.tools import docgen_tools

NAME = "智学 MCP DocGen"
INSTRUCTIONS = (
    "提供课本知识检索与 Word 文档生成能力。"
    "search_textbook 用于回答'课本上怎么讲'；"
    "render_word / build_study_plan / build_lecture_note 用于产出可下载的 .docx。"
)


def register(mcp: Any) -> None:
    @mcp.tool
    def search_textbook(query: str, subject: str | None = None, k: int = 5) -> list[dict[str, Any]]:
        """在课本向量库里检索与 query 最相关的教学段落。"""
        return docgen_tools.search_textbook(query, subject=subject, k=k)

    @mcp.tool
    def list_templates() -> list[dict[str, Any]]:
        """列出可用的 Word 模板（doc_type 用于 render_word）。"""
        return docgen_tools.list_templates()

    @mcp.tool
    def render_word(doc_type: str, data: dict[str, Any], output_name: str | None = None) -> dict[str, Any]:
        """用 data 填充指定模板，生成一份 .docx 并返回文件路径。

        doc_type 取值：study_plan / lecture / mistake_report / exam_paper。
        """
        return docgen_tools.render_word(doc_type, data, output_name=output_name)

    @mcp.tool
    def build_study_plan(
        topic: str,
        subject: str | None = None,
        student_name: str = "同学",
        class_name: str = "—",
        days: int = 7,
        goal: str | None = None,
    ) -> dict[str, Any]:
        """按知识点生成一份个性化学习计划 Word 文档。"""
        return docgen_tools.build_study_plan(
            topic, subject=subject, student_name=student_name,
            class_name=class_name, days=days, goal=goal,
        )

    @mcp.tool
    def build_lecture_note(
        knowledge_point: str,
        subject: str | None = None,
        explanation: str = "",
        example: str = "",
        exercises: str = "",
        pitfall: str = "",
        difficulty: str = "中等",
    ) -> dict[str, Any]:
        """生成一份知识点讲义 Word 文档。"""
        return docgen_tools.build_lecture_note(
            knowledge_point, subject=subject, explanation=explanation, example=example,
            exercises=exercises, pitfall=pitfall, difficulty=difficulty,
        )


def main() -> None:
    serve(
        service="MCP DocGen",
        name=NAME,
        instructions=INSTRUCTIONS,
        register=register,
        default_port=get_settings().ports.docgen_mcp,
    )


if __name__ == "__main__":
    main()
