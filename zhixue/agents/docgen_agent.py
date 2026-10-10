"""文档生成 Agent（DocGenServer :5010）。

链路：课本向量库检索（MCP DocGen）-> LLM 组织内容 -> Word 模板渲染。
"""

from __future__ import annotations

from typing import Any

from zhixue.agents.base import BaseAgent
from zhixue.schemas import Intent, TaskRequest


class DocGenAgent(BaseAgent):
    key = "docgen"
    name = "文档生成 Agent"
    intent = Intent.DOC_GEN
    description = "检索课本知识并生成学习计划、知识点讲义等 Word 文档。"
    instructions = (
        "你负责把课本知识整理成结构清晰的教学文档："
        "先给出概念讲解，再给典型示例，最后布置练习并提示易错点。"
    )

    #: 支持的文档类型 -> 渲染工具名
    DOC_TYPES = {
        "study_plan": "build_study_plan",
        "lecture": "build_lecture_note",
        "note": "build_lecture_note",
    }

    def run(self, request: TaskRequest) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        topic = self.slot(request, "topic") or self.slot_text(request) or "综合复习"
        subject = self.slot(request, "subject")
        doc_type = str(self.slot(request, "doc_type", "lecture"))
        student_name = self.slot(request, "student_name", "同学")
        class_name = self.slot(request, "class_name", "—")
        days = int(self.slot(request, "days", 7) or 7)

        # 1) RAG 课本检索（走 MCP DocGen -> 课本向量库）
        chunks = self.tools.call("search_textbook", query=topic, subject=subject, k=4) or []
        context = "\n\n".join(
            f"【{c.get('title', '')}】{c.get('content', '')}" for c in chunks
        ) or "（课本库暂无命中，请基于通用教学经验作答。）"
        backend = chunks[0].get("backend", "-") if chunks else "-"

        # 2) LLM 组织教学内容
        composed = self.chat_json(
            "请基于下面的课本资料，为知识点「{topic}」准备教学材料。\n"
            "资料：\n{context}\n\n"
            "输出 JSON：{{\"explanation\": \"概念讲解 150 字以内\", "
            "\"example\": \"一个典型示例\", \"exercises\": \"2 道练习（含答案）\", "
            "\"pitfall\": \"最容易踩的坑\", \"summary\": \"给学生的一句话总结\"}}".format(
                topic=topic, context=context[:3000]
            ),
            fallback=self._fallback_content(topic, chunks),
        )

        # 3) 渲染 Word（走 MCP DocGen -> Word 模板库）
        tool = self.DOC_TYPES.get(doc_type, "build_lecture_note")
        if tool == "build_study_plan":
            doc = self.tools.call(
                "build_study_plan",
                topic=topic,
                subject=subject,
                student_name=student_name,
                class_name=class_name,
                days=days,
                goal=composed.get("summary") or None,
            )
        else:
            doc = self.tools.call(
                "build_lecture_note",
                knowledge_point=topic,
                subject=subject,
                explanation=composed.get("explanation", ""),
                example=composed.get("example", ""),
                exercises=composed.get("exercises", ""),
                pitfall=composed.get("pitfall", ""),
            )

        summary = composed.get("summary") or f"已为你整理「{topic}」的学习材料。"
        text = (
            f"{summary}\n\n"
            f"参考资料：命中课本片段 {len(chunks)} 段（检索通道：{backend}）。\n"
            f"文档已生成：{doc['filename']}"
        )
        data = {
            "topic": topic,
            "subject": subject,
            "doc_type": doc_type,
            "content": composed,
            "references": [
                {
                    "title": c.get("title"),
                    "chapter": c.get("chapter"),
                    "score": c.get("score"),
                }
                for c in chunks
            ],
            "retrieval_backend": backend,
        }
        artifacts = [
            {
                "type": "docx",
                "name": doc["filename"],
                "path": doc["path"],
                "url": f"/api/files/{doc['filename']}",
            }
        ]
        return text, data, artifacts

    @staticmethod
    def _fallback_content(topic: str, chunks: list[dict[str, Any]]) -> dict[str, str]:
        """没有 LLM 时，直接用课本文本拼一份可用的讲义。"""
        body = "\n\n".join(c.get("content", "") for c in chunks[:2])
        return {
            "explanation": body or f"「{topic}」的核心概念与适用场景。",
            "example": f"结合课程示例，说明「{topic}」在实际代码/工程中的用法。",
            "exercises": f"练习一：用自己的话解释「{topic}」。\n练习二：举一个使用「{topic}」的例子。",
            "pitfall": f"注意「{topic}」的边界条件与常见误用。",
            "summary": f"已为你整理「{topic}」的知识讲义与练习。",
        }


def main() -> None:
    DocGenAgent().serve()


if __name__ == "__main__":
    main()
