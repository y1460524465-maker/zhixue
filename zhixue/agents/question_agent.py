"""出题 Agent（QuestionServer :5011）。

两个入口，一条出口。

**入口一（标签式）**：用户直接说要哪个知识点的题
    -> 解析知识点 -> 题库检索 -> 出题

**入口二（样本式）**：用户要做错的题
    -> 通过 A2A 找学情 Agent 要错题**指针**（q_id / kp_id / 错次 / 掌握度）
    -> 拿指针回**自己的题库**换实体（题干、选项、答案）
    -> 出题

入口二遵守"数据归谁管就通过谁拿"：错题记录库归学情 Agent，
出题 Agent 不直连，只通过 A2A 要；而题库本来就是出题 Agent 的地盘。

出口只有一条：成套题目（下成作业，或导出试卷）。
"""

from __future__ import annotations

from typing import Any

from zhixue.a2a.client import A2AClient
from zhixue.agents.base import BaseAgent
from zhixue.schemas import Intent, TaskRequest, TaskResult, wants_mistakes
from zhixue.tool_client import run_async

#: 交互记忆窗口：这么多天内出过的题不再重复出
REPEAT_WINDOW_DAYS = 30


class QuestionAgent(BaseAgent):
    key = "question"
    name = "出题 Agent"
    intent = Intent.QUESTION_GEN
    description = "按知识点出题，或针对学生的错题出题；可直接下成作业或导出试卷。"
    instructions = (
        "你负责组卷：先确认要考什么，再按难度梯度选题，"
        "确保覆盖概念理解与应用能力，最后说明这张卷子的考察重点。"
    )

    # ------------------------------------------------------------------ #
    # 入口分流
    # ------------------------------------------------------------------ #
    def run(self, request: TaskRequest) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        if self._wants_mistakes(request):
            return self._build_from_mistakes(request)
        return self._build_from_knowledge_point(request)

    def _wants_mistakes(self, request: TaskRequest) -> bool:
        """判断这次是"针对错题出题"还是"按知识点出题"。"""
        source = self.slot(request, "source")
        if source:
            return str(source) == "mistakes"
        haystack = " ".join(
            str(v) for v in request.slots.values() if isinstance(v, (str, int, float))
        )
        return wants_mistakes(haystack)

    # ------------------------------------------------------------------ #
    # 入口二：针对错题出题
    # ------------------------------------------------------------------ #
    def _build_from_mistakes(
        self, request: TaskRequest
    ) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        student_id = self.slot(request, "student_id")
        subject = self.slot(request, "subject")
        count = int(self.slot(request, "count", 5) or 5)
        mode = str(self.slot(request, "mode", "homework"))
        user_id = request.user_id

        if not student_id:
            raise ValueError("按错题出题需要先指定学生（学号，如 S00001）")

        # 1) 向学情 Agent 要错题指针（只拿事实）
        pointers = self._fetch_mistakes(student_id, subject, limit=max(count * 3, 15))
        if not pointers:
            raise ValueError(
                f"{student_id} 的错题记录是空的——要么还没批改过作业，"
                "要么这个学生目前没有错题。"
            )

        # 2) 指针换实体：回自己的题库
        q_ids = [str(p["q_id"]) for p in pointers]
        questions = self.tools.call("get_questions_by_ids", question_ids=q_ids) or []
        if not questions:
            raise ValueError("错题对应的题目在题库里查不到，题库可能被重建过")

        # 3) 交互记忆：排除最近已经出过的，避免反复刷同一批题
        issued = set(
            self.tools.call(
                "recently_issued_q_ids", student_id=student_id, days=REPEAT_WINDOW_DAYS
            ) or []
        )
        fresh = [q for q in questions if q["q_id"] not in issued]
        reused = not fresh
        if reused:
            fresh = questions  # 全在窗口内出过，允许重复但要说明
        picked = fresh[:count]

        # 4) 落库 / 导出
        title = f"错题巩固（{len(picked)} 题）"
        homework, doc, artifacts = self._issue(request, title, picked, subject, mode, user_id)

        # 5) 交互记忆：记下这次发出去的题
        self._record_issued(student_id, [q["q_id"] for q in picked], homework, "mistake")

        pairs = list(zip(picked, pointers))
        comment = self.chat(
            f"学生 {student_id} 的错题清单（按错次从多到少）：\n"
            + "\n".join(f"- {q['stem'][:50]}（错过 {p.get('wrong_count', 1)} 次）" for q, p in pairs)
            + "\n\n请用 120 字以内说明这次巩固练习的安排思路。",
            fallback=(
                f"这次从 {student_id} 的错题里挑了 {len(picked)} 道，"
                "按错误次数从多到少排列，建议每题做完都对照解析复盘一次。"
            ),
        )

        where = (
            f"已下成作业：{homework['homework_id']}"
            if homework
            else f"试卷已导出：{doc['filename'] if doc else '—'}"
        )
        text = (
            f"{comment}\n\n"
            f"题目来源：{student_id} 的错题记录（共 {len(pointers)} 条，本次选用 {len(picked)} 道）。\n"
            f"{where}"
            + ("\n（注意：这些题近期已经出过，本次为重复巩固。）" if reused else "")
        )
        data = {
            "source": "mistakes",
            "student_id": student_id,
            "subject": subject,
            "mistake_count": len(pointers),
            "count": len(picked),
            "reused": reused,
            "homework": homework,
            "document": doc,
            "questions": picked,
            "mistakes": pointers,
        }
        return text, data, artifacts

    def _fetch_mistakes(
        self, student_id: str, subject: str | None, limit: int = 15
    ) -> list[dict[str, Any]]:
        """通过 A2A 找学情 Agent 要错题；不通就在本地直连同一套工具。"""
        request = TaskRequest(
            intent=Intent.ANALYSIS,
            slots={
                "student_id": student_id,
                "subject": subject,
                "limit": limit,
                "action": "list_mistakes",
            },
        )
        try:
            result: TaskResult = run_async(A2AClient().send("analysis", request))
            if result.status == "ok":
                return list(result.data.get("mistakes") or [])
            self.logger.warning("学情 Agent 返回异常: %s", result.error)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("A2A 取错题失败(%s)，改为本地读取", exc)

        fallback = self.tools.call_local(
            "list_mistakes", student_id=student_id, subject=subject, limit=limit
        )
        return list(fallback.get("mistakes") or [])

    # ------------------------------------------------------------------ #
    # 入口一：按知识点出题
    # ------------------------------------------------------------------ #
    def _build_from_knowledge_point(
        self, request: TaskRequest
    ) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
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
        student_id = self.slot(request, "student_id")
        user_id = request.user_id

        # 1) 知识点解析
        kp = self.tools.call(
            "resolve_knowledge_point", knowledge_point=knowledge_point, subject=subject
        )
        kp_id = kp["kp_id"] if kp else None
        subject = subject or (kp["subject"] if kp else None)

        # 2) 题库语义检索（相似题参考）
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

        title = f"{knowledge_point} 专项练习（{len(questions)} 题）"
        homework, doc, artifacts = self._issue(request, title, questions, subject, mode, user_id)

        # 4) 交互记忆：有学生上下文时记一笔
        if student_id:
            self._record_issued(
                student_id, [q["q_id"] for q in questions], homework, "homework"
            )

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
            "source": "knowledge_point",
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

    # ------------------------------------------------------------------ #
    # 公用
    # ------------------------------------------------------------------ #
    def _issue(
        self,
        request: TaskRequest,
        title: str,
        questions: list[dict[str, Any]],
        subject: str | None,
        mode: str,
        subdir: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
        """落成作业或导出试卷。"""
        artifacts: list[dict[str, Any]] = []
        homework: dict[str, Any] | None = None
        doc: dict[str, Any] | None = None
        question_ids = [q["q_id"] for q in questions]

        if mode == "exam":
            doc = self.tools.call(
                "build_exam_from_ids",
                title=title,
                question_ids=question_ids,
                subject=subject or "",
                duration=60,
                subdir=subdir,
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
                kp_id=self.slot(request, "kp_id")
                or (questions[0]["kp_id"] if questions else None),
            )
        return homework, doc, artifacts

    def _record_issued(
        self,
        student_id: str,
        question_ids: list[str],
        homework: dict[str, Any] | None,
        source: str,
    ) -> None:
        try:
            self.tools.call(
                "record_issued_questions",
                student_id=student_id,
                question_ids=question_ids,
                homework_id=(homework or {}).get("homework_id"),
                source=source,
            )
        except Exception as exc:  # noqa: BLE001 - 记忆失败不该影响出题
            self.logger.warning("记录出题历史失败: %s", exc)


def main() -> None:
    QuestionAgent().serve()


if __name__ == "__main__":
    main()
