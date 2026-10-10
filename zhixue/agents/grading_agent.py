"""作业批改 Agent（GradingServer :5012）。

链路：OCR 识别 -> 答案比对 -> 落库；随后通过 A2AClient 横向通知
学情分析 Agent 写入错题记录（架构图上那条虚线）。
"""

from __future__ import annotations

from typing import Any

from zhixue.a2a.client import A2AClient
from zhixue.agents.base import BaseAgent
from zhixue.schemas import Intent, TaskRequest, TaskResult
from zhixue.tool_client import run_async


class GradingAgent(BaseAgent):
    key = "grading"
    name = "作业批改 Agent"
    intent = Intent.GRADING
    description = "识别答题卡、自动批改作业，并把错题同步给学情分析。"
    instructions = (
        "你负责讲评作业：先报整体得分，再指出错题的共性问题，"
        "最后给出可执行的改进建议。语气要鼓励学生。"
    )

    def run(self, request: TaskRequest) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        student_id = self.slot(request, "student_id")
        homework_id = self.slot(request, "homework_id")
        file_path = self.slot(request, "file_path") or self.slot(request, "file")
        answers = self.slot(request, "student_answers")
        use_llm = bool(self.slot(request, "use_llm", True))

        if not student_id or not homework_id:
            raise ValueError("批改需要 student_id 与 homework_id")

        if not answers and not file_path:
            # 既没有图片也没有逐题作答时，复用库里最近一次答题记录（等价于"重新批改"）
            existing = self.tools.call(
                "list_student_answers", homework_id=homework_id, student_id=student_id
            ) or []
            if existing:
                answers = {
                    str(index + 1): row["student_answer"]
                    for index, row in enumerate(existing)
                }
            else:
                return (
                    f"没有找到 {student_id} 对作业 {homework_id} 的作答记录。\n\n"
                    "请二选一后重试：\n"
                    "1) 上传答题卡图片（点左下角「上传答题卡」）；\n"
                    "2) 直接告诉我逐题作答，例如「1:B 2:装饰器是…」。",
                    {
                        "student_id": student_id,
                        "homework_id": homework_id,
                        "reason": "no_submission",
                    },
                    [],
                )

        # 1) 完整批改（内部会按需 OCR）
        report = self.tools.call(
            "grade_submission",
            homework_id=homework_id,
            student_id=student_id,
            file_path=file_path,
            student_answers=answers,
            use_llm=use_llm,
        )

        # 2) 架构图虚线：批改结果 -> 学情分析 Agent 写入错题记录库
        mistake_sync = self._notify_analysis(student_id, homework_id)

        # 3) LLM 讲评
        wrong = [d for d in report["details"] if not d["is_correct"]]
        wrong_lines = "\n".join(
            f"- {d['stem'][:50]}｜作答：{d['student_answer'][:40]}｜应为：{d['std_answer'][:40]}"
            for d in wrong
        ) or "（本次全对）"
        comment = self.chat(
            f"学生 {student_id} 的作业《{report['homework_title']}》"
            f"得分 {report['score']}/{report['full_score']}（得分率 {report['rate'] * 100:.0f}%）。\n"
            f"错题：\n{wrong_lines}\n\n"
            "请用 150 字以内做一次讲评：先肯定，再指出问题，最后给一条具体改进建议。",
            fallback=(
                f"本次得分 {report['score']}/{report['full_score']}。"
                f"错题 {len(wrong)} 道，建议对照解析逐题复盘。"
            ),
        )

        text = (
            f"{comment}\n\n"
            f"批改结果：{report['score']}/{report['full_score']}"
            f"（得分率 {report['rate'] * 100:.0f}%），错题 {len(wrong)} 道。\n"
            f"错题已同步至学情分析：{mistake_sync.get('mistakes', 0)} 条"
            f"（通道：{mistake_sync.get('channel', '-')}）。"
        )
        data = {
            "submission_id": report.get("submission_id"),
            "score": report["score"],
            "full_score": report["full_score"],
            "rate": report["rate"],
            "kp_scores": report["kp_scores"],
            "details": report["details"],
            "ocr": report["ocr"],
            "mistake_sync": mistake_sync,
        }
        artifacts: list[dict[str, Any]] = []
        if file_path:
            artifacts.append({"type": "image", "name": str(file_path).split("\\")[-1], "path": str(file_path)})
        return text, data, artifacts

    def _notify_analysis(self, student_id: str, homework_id: str) -> dict[str, Any]:
        """通过 A2A 让学情分析 Agent 写错题记录；失败就在本地直接写。"""
        request = TaskRequest(
            intent=Intent.ANALYSIS,
            slots={
                "student_id": student_id,
                "homework_id": homework_id,
                "action": "write_mistakes",
            },
        )
        try:
            result: TaskResult = run_async(A2AClient().send("analysis", request))
            if result.status == "ok":
                return {**result.data, "channel": "a2a"}
            self.logger.warning("学情分析 Agent 返回异常: %s", result.error)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("A2A 通知学情分析失败(%s)，改为本地落库", exc)

        fallback = self.tools.call(
            "sync_mistake_records", student_id=student_id, homework_id=homework_id
        )
        return {**fallback, "channel": "local"}


def main() -> None:
    GradingAgent().serve()


if __name__ == "__main__":
    main()
