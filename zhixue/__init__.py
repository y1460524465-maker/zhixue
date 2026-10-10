"""智学 —— 多 Agent 协同的智慧教学问答与作业批改系统。

分层结构（与架构图一一对应）：:

    主应用层      zhixue.app.main            :8000   LLM Router + AgentNetwork
    A2A Agent 层  zhixue.agents.*            :5010~5013
    MCP 服务层    zhixue.mcp_servers.*       :8010~8013  (/mcp)
    工具与数据层  zhixue.tools.*             课本/题库向量库、MySQL、OCR、Word

其中 ``zhixue.tools`` 只放纯业务逻辑，不依赖任何协议库，
所以既能被 MCP Server 包成工具，也能被单测直接调用。
"""

__version__ = "1.0.0"
APP_NAME = "智学"

__all__ = ["APP_NAME", "__version__"]
