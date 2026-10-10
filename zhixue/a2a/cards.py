"""Agent Card：A2A 里描述"这个 Agent 能干什么"的元数据。"""

from __future__ import annotations

from typing import Any

from zhixue.config import get_settings

#: 每个 Agent 对外声明的技能
AGENT_SKILLS: dict[str, list[dict[str, Any]]] = {
    "docgen": [
        {
            "id": "textbook_rag",
            "name": "课本知识检索",
            "description": "基于课本向量库检索教学段落，用于答疑与备课。",
            "tags": ["RAG", "向量检索", "课本"],
            "examples": ["装饰器的工作原理是什么", "HDFS 为什么不适合小文件"],
        },
        {
            "id": "word_docgen",
            "name": "Word 文档生成",
            "description": "用模板库渲染学习计划、讲义、错题报告、试卷等 .docx。",
            "tags": ["Word", "模板", "文档"],
            "examples": ["帮我出一份装饰器的学习计划", "生成红黑树知识点讲义"],
        },
    ],
    "question": [
        {
            "id": "question_rag",
            "name": "题库语义检索",
            "description": "在题目向量库中检索相似题目与解析。",
            "tags": ["RAG", "题库"],
            "examples": ["找几道关于线程池的题"],
        },
        {
            "id": "question_generate",
            "name": "智能出题",
            "description": "按知识点、题型、难度选题组卷，可下成作业或导出试卷。",
            "tags": ["出题", "组卷"],
            "examples": ["给 Python 装饰器出 5 道题", "出一套 Java 并发测验"],
        },
    ],
    "grading": [
        {
            "id": "ocr_homework",
            "name": "答题卡 OCR",
            "description": "识别答题卡图片，抽取题号与作答。",
            "tags": ["OCR", "批改"],
            "examples": ["识别这张答题卡"],
        },
        {
            "id": "auto_grading",
            "name": "自动批改",
            "description": "客观题规则比对、主观题 LLM 评分，输出逐题得分与评语。",
            "tags": ["批改", "评分"],
            "examples": ["批改 S00001 的 HW00001"],
        },
    ],
    "analysis": [
        {
            "id": "learning_profile",
            "name": "学情分析",
            "description": "生成学生画像、薄弱知识点、成绩趋势与班级对比。",
            "tags": ["学情", "成绩", "错题"],
            "examples": ["分析一下 S00001 最近的学习情况", "我哪个知识点最薄弱"],
        },
        {
            "id": "text_to_sql",
            "name": "Text-to-SQL",
            "description": "把自然语言统计需求翻译成只读 SQL 并执行。",
            "tags": ["SQL", "统计"],
            "examples": ["各学科平均分是多少"],
        },
    ],
}


def card_dict(agent: str, name: str, description: str, url: str) -> dict[str, Any]:
    """A2A Agent Card 的字典形式（SDK 缺失时直接返回它）。"""
    return {
        "protocolVersion": "1.0",
        "name": name,
        "description": description,
        "version": "1.0.0",
        "url": url,
        "preferredTransport": "JSONRPC",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": AGENT_SKILLS.get(agent, []),
    }


def build_sdk_card(agent: str, name: str, description: str, url: str) -> Any | None:
    """构造 a2a-sdk 的 ``AgentCard``（protobuf）。没装 SDK 返回 None。"""
    try:
        from a2a.types import (
            AgentCapabilities,
            AgentCard,
            AgentInterface,
            AgentSkill,
        )
    except ImportError:
        return None

    skills = [
        AgentSkill(
            id=item["id"],
            name=item["name"],
            description=item["description"],
            tags=list(item.get("tags") or []),
            examples=list(item.get("examples") or []),
            input_modes=["text/plain"],
            output_modes=["application/json"],
        )
        for item in AGENT_SKILLS.get(agent, [])
    ]
    return AgentCard(
        name=name,
        description=description,
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(
                url=url.rstrip("/") or get_settings().url("main"),
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["text/plain", "application/json"],
        default_output_modes=["application/json"],
        skills=skills,
    )


__all__ = ["AGENT_SKILLS", "card_dict", "build_sdk_card"]
