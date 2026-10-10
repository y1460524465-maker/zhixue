"""MCP Analysis —— 学情分析工具服务（:8013/mcp）。

对应架构图的 ``Text-to-SQL`` -> ``学生成绩库`` / ``错题记录库``。
"""

from __future__ import annotations

from typing import Any

from zhixue.config import get_settings
from zhixue.mcp_servers._runner import serve
from zhixue.tools import analysis_tools

NAME = "智学 MCP Analysis"
INSTRUCTIONS = (
    "提供学情分析能力：自然语言转 SQL、学生画像、薄弱知识点、成绩趋势、班级对比。"
    "涉及临时统计问题时用 text_to_sql；常规学情问题直接调用 student_profile 等固定视图。"
)


def register(mcp: Any) -> None:
    @mcp.tool
    def text_to_sql(question: str, execute: bool = True) -> dict[str, Any]:
        """把自然语言问题翻译成只读 SQL；execute=True 时顺带执行并返回结果。"""
        return analysis_tools.text_to_sql(question, execute=execute)

    @mcp.tool
    def run_sql(sql: str) -> dict[str, Any]:
        """执行一条只读 SQL（写操作会被拒绝）。"""
        return analysis_tools.run_sql(sql)

    @mcp.tool
    def student_profile(student_id: str, top_n: int = 5) -> dict[str, Any]:
        """学生画像：基础信息 + 成绩概览 + 知识点掌握度 + 高频错题。"""
        return analysis_tools.student_profile(student_id, top_n=top_n)

    @mcp.tool
    def weak_knowledge_points(student_id: str, top_n: int = 3) -> list[dict[str, Any]]:
        """找出最薄弱的 N 个知识点。"""
        return analysis_tools.weak_knowledge_points(student_id, top_n=top_n)

    @mcp.tool
    def score_trend(student_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """按时间正序返回成绩趋势。"""
        return analysis_tools.score_trend(student_id, limit=limit)

    @mcp.tool
    def class_comparison(student_id: str) -> dict[str, Any]:
        """个人得分率与班级平均分对比。"""
        return analysis_tools.class_comparison(student_id)

    @mcp.tool
    def frequent_mistakes(subject: str | None = None, top_n: int = 10) -> list[dict[str, Any]]:
        """高频错题排行（教研视角）。"""
        return analysis_tools.frequent_mistakes(subject=subject, top_n=top_n)

    @mcp.tool
    def write_mistake_records(student_id: str, homework_id: str | None = None) -> dict[str, Any]:
        """接收批改结果，写入错题记录库（批改 Agent 会通过 A2A 调用这里）。"""
        return analysis_tools.write_mistake_records(student_id, homework_id)

    @mcp.tool
    def list_mistakes(
        student_id: str,
        subject: str | None = None,
        kp_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """读某个学生的错题清单（只返回题目编号与错次等事实，题干请回题库取）。"""
        return analysis_tools.list_mistakes(
            student_id, subject=subject, kp_id=kp_id, limit=limit
        )


def main() -> None:
    serve(
        service="MCP Analysis",
        name=NAME,
        instructions=INSTRUCTIONS,
        register=register,
        default_port=get_settings().ports.analysis_mcp,
    )


if __name__ == "__main__":
    main()
