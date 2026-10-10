"""工具与数据层：智学所有"真干活"的函数都在这里。

刻意不依赖任何协议库（MCP / A2A），因此：

* MCP Server 可以把它包成工具暴露出去；
* Agent 可以在本地模式下直接调用；
* 单元测试也能直接跑，不用起任何服务。
"""

from zhixue.tools import analysis_tools, docgen_tools, grading_tools, question_tools

__all__ = ["docgen_tools", "question_tools", "grading_tools", "analysis_tools"]
