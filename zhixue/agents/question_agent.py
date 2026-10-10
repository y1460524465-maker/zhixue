"""出题 Agent（QuestionServer :5011）。

链路：知识点解析 -> 题库向量检索 + 结构化选题 -> 作业下发 / 试卷导出。
"""

from __future__ import annotations

from typing import Any

from zhixue.agents.base import BaseAgent
from zhixue.schemas import Intent, TaskRequest


class QuestionAgent(BaseAgent):
    key = "question"
    name = "出题 Agent"
    intent = Intent.QUESTION_GEN
    description = "按知识点与难度智能选题、组卷，可直接下成作业或导出试卷。"
    instructions = (
        "你负责组卷：先确认知识点，再按难度梯度选题，"
        "确保覆盖概念理解与应用能力，最后说明这张卷子的考察重点。"
    )

    def run(self, request: TaskRequest) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        knowledge_point = (
            self.slot(request, "knowledge_point")
            or self.slot(request, "topic")
            or self.slot_text(request)
            or "综合"
        )
        subject = self.slot(request, "subject")
        count = int(self.slot(request, "count", 5) or 5)
        q_type = self.slot(request, "q_type")
        difficulty = self.slot(request, "difficulty")
        mode = str(self.slot(request, "mode", "homework"))

        # 1) 知识点解析
        kp = self.tools.call("resolve_knowledge_point", knowledge_point=knowledge_point, subject=subject)
        kp_id = kp["kp_id"] if kp else None
        subject = subject or (kp["subject"] if kp else None)

        # 2) RAG 题库检索（相似题参考）
        similar = self.tools.call(
            "search_question_bank", query=knowledge_point, subject=subject, k=3
        ) or []

        # 3) 结构化选题
        questions = self.tools.call(
            "select_questions",
            kp_id=kp_id,
            subject=subject,
            q_type=q_type,
            difficulty=int(difficulty) if difficulty else None,
            n=count,
        ) or []
        if not questions:
            raise ValueError(f"题库里没有找到与「{knowledge_point}」匹配的题目")

        question_ids = [q["q_id"] for q in questions]
        title = f"{knowledge_point} 专项练习（{len(questions)} 题）"

        # 4) 落库 / 导出
        artifacts: list[dict[str, Any]] = []
        homework: dict[str, Any] | None = None
        doc: dict[str, Any] | None = None
        if mode == "exam":
            doc = self.tools.call(
                "build_exam_from_ids",
                title=title,
                question_ids=question_ids,
                subject=subject or "",
                duration=60,
            )
            artifacts.append(
                {
                    "type": "docx",
                    "name": doc["filename"],
                    "path": doc["path"],
                    "url": f"/api/files/{doc['filename']}",
                }
            )
        else:
            homework = self.tools.call(
                "create_homework",
                title=title,
                question_ids=question_ids,
                subject=subject,
                kp_id=kp_id,
            )

        # 5) LLM 写出题说明
        outline = "\n".join(
            f"{i + 1}. [{q['q_type']}/难度{q['difficulty']}] {q['stem'][:60]}"
            for i, q in enumerate(questions)
        )
        comment = self.chat(
            f"下面是一份针对「{knowledge_point}」的练习题清单：\n{outline}\n\n"
            "请用 120 字以内说明这份练习的考察重点和做题建议。",
            fallback=f"本次练习覆盖「{knowledge_point}」的核心考点，建议先做概念题再攻简答题。",
        )

        where = (
            f"已下发给全班的作业编号：{homework['homework_id']}"
            if homework
            else f"试卷已导出：{doc['filename'] if doc else '—'}"
        )
        text = f"{comment}\n\n共 {len(questions)} 题，{where}"
        data = {
            "knowledge_point": knowledge_point,
            "kp_id": kp_id,
            "subject": subject,
            "count": len(questions),
            "homework": homework,
            "document": doc,
            "questions": questions,
            "similar": [
                {"q_id": s["q_id"], "stem": s["stem"][:80], "score": s.get("score")}
                for s in similar
            ],
        }
        return text, data, artifacts


def main() -> None:
    QuestionAgent().serve()


if __name__ == "__main__":
    main()
