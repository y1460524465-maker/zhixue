"""A2A Agent 层：四个业务 Agent。

===============  ======  ==========================
Agent            端口    依赖的 MCP Server
===============  ======  ==========================
DocGenServer     5010    MCP DocGen   :8010
QuestionServer   5011    MCP Question :8011
GradingServer    5012    MCP Grading  :8012
AnalysisServer   5013    MCP Analysis :8013
===============  ======  ==========================

Agent 之间还会横向调用（架构图上的虚线）：
批改 Agent 把错题结果交给学情分析 Agent 落库。
"""
