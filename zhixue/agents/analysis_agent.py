"""学情分析 Agent（AnalysisServer :5013）。

链路：Text-to-SQL / 固定分析视图 -> 学生成绩库 + 错题记录库 -> LLM 学情报告。
同时承接批改 Agent 的 A2A 请求，负责写入错题记录库。
"""

from __future__ import annotations

from typing import Any

from zhixue.agents.base import BaseAgent
from zhixue.schemas import Intent, TaskRequest


class AnalysisAgent(BaseAgent):
    key = "analysis"
    name = "学情分析 Agent"
    intent = Intent.ANALYSIS
    description = "分析学生成绩与错题，输出薄弱知识点、趋势和提升建议。"
    instructions = (
        "你负责学情诊断：用数据说话，指出薄弱知识点和变化趋势，"
        "给出的建议要具体到'下一步做什么'。"
    )

    def run(self, request: TaskRequest) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        action = self.slot(request, "action")
        student_id = self.slot(request, "student_id")
        homework_id = self.slot(request, "homework_id")

        # 批改 Agent 通过 A2A 调过来：只负责写错题记录库
        if action == "write_mistakes":
            if not student_id:
                raise ValueError("写入错题记录需要 student_id")
            synced = self.tools.call(
                "write_mistake_records", student_id=student_id, homework_id=homework_id
            )
            return (
                f"已为 {student_id} 同步错题 {synced.get('mistakes', 0)} 条。",
                synced,
                [],
            )

        # 出题 Agent 通过 A2A 调过来：只交出事实（错题指针），不做任何判断
        if action == "list_mistakes":
            if not student_id:
                raise ValueError("读取错题清单需要 student_id")
            payload = self.tools.call(
                "list_mistakes",
                student_id=student_id,
                subject=self.slot(request, "subject"),
                limit=int(self.slot(request, "limit", 20) or 20),
            )
            return (
                f"已读取 {student_id} 的错题 {payload.get('count', 0)} 条。",
                payload,
                [],
            )

        if not student_id:
            raise ValueError("学情分析需要 student_id（或先在设置里选择学生）")

        # 1) 固定分析视图（走 MCP Analysis -> 学生成绩库 / 错题记录库）
        profile = self.tools.call("student_profile", student_id=student_id, top_n=5)
        trend = self.tools.call("score_trend", student_id=student_id, limit=8) or []
        comparison = self.tools.call("class_comparison", student_id=student_id)

        # 2) 可选：自然语言统计（Text-to-SQL）
        ad_hoc: dict[str, Any] | None = None
        question = self.slot(request, "question") or self.slot(request, "raw_input")
        if question and student_id not in str(question):
            question = f"{question}（学生 {student_id}）"
        if question:
            ad_hoc = self.tools.call("text_to_sql", question=question, execute=True)

        # 3) 组装报告
        weak = profile.get("weak_points", [])
        weak_lines = "\n".join(
            f"- {w['name']}（{w['subject']}）掌握度 {w['rate'] * 100:.0f}%" for w in weak
        ) or "（暂无足够数据）"
        overview = profile["overview"]

        report = self.chat(
            f"学生：{profile['student']['name']}（{profile['student']['class_name']}）\n"
            f"已批改作业 {overview['homework_count']} 次，平均得分率 {overview['avg_rate'] * 100:.0f}%，"
            f"最好 {overview['best_rate'] * 100:.0f}%，最差 {overview['worst_rate'] * 100:.0f}%。\n"
            f"班级平均得分率 {comparison['class_rate'] * 100:.0f}%，"
            f"本人 {comparison['my_rate'] * 100:.0f}%。\n"
            f"薄弱知识点：\n{weak_lines}\n\n"
            "请输出一份 200 字以内的学情诊断，包含：整体评价、最需要补的 2 个知识点、"
            "接下来一周的具体行动建议。",
            fallback=(
                f"整体得分率 {overview['avg_rate'] * 100:.0f}%，"
                f"{comparison['position']}（{comparison['gap'] * 100:+.0f} 个百分点）。"
                f"建议优先补强：{'、'.join(w['name'] for w in weak[:2]) or '暂无'}，"
                "每天用 30 分钟做针对性练习并整理错题。"
            ),
        )

        text = (
            f"{report}\n\n"
            f"数据来源：成绩 {overview['homework_count']} 次，"
            f"错题 {len(profile['top_mistakes'])} 条高频记录。"
        )
        data = {
            "student": profile["student"],
            "overview": overview,
            "weak_points": weak,
            "strong_points": profile["strong_points"],
            "mastery": profile["mastery"],
            "top_mistakes": profile["top_mistakes"],
            "trend": trend,
            "comparison": comparison,
            "ad_hoc_sql": ad_hoc,
        }
        artifacts: list[dict[str, Any]] = []
        return text, data, artifacts


def main() -> None:
    AnalysisAgent().serve()


if __name__ == "__main__":
    main()
