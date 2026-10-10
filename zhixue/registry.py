"""服务注册表：意图 -> Agent 的静态路由（架构图里 AgentNetwork 那张表）。"""

from __future__ import annotations

from zhixue.config import get_settings
from zhixue.schemas import Intent

#: 意图 -> Agent 的名字（对应 Settings.ports 的别名）
INTENT_TO_AGENT: dict[Intent, str] = {
    Intent.DOC_GEN: "docgen",
    Intent.QUESTION_GEN: "question",
    Intent.GRADING: "grading",
    Intent.ANALYSIS: "analysis",
}

#: Agent 名字 -> 它自己挂的 MCP Server
AGENT_TO_MCP: dict[str, str] = {
    "docgen": "docgen_mcp",
    "question": "question_mcp",
    "grading": "grading_mcp",
    "analysis": "analysis_mcp",
}

AGENT_DISPLAY_NAME: dict[str, str] = {
    "docgen": "文档生成 Agent",
    "question": "出题 Agent",
    "grading": "作业批改 Agent",
    "analysis": "学情分析 Agent",
}


def agent_url(agent: str) -> str:
    return get_settings().url(agent)


def mcp_url(agent: str) -> str:
    return get_settings().mcp_url(AGENT_TO_MCP[agent])


__all__ = [
    "INTENT_TO_AGENT",
    "AGENT_TO_MCP",
    "AGENT_DISPLAY_NAME",
    "agent_url",
    "mcp_url",
]
