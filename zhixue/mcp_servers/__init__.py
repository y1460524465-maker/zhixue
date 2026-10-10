"""MCP 服务层：把 :mod:`zhixue.tools` 里的函数暴露成 MCP 工具。

四个 Server 与架构图一一对应：

===============  ======  ==================================
服务             端口    工具来源
===============  ======  ==================================
MCP DocGen       8010    ``zhixue.tools.docgen_tools``
MCP Question     8011    ``zhixue.tools.question_tools``
MCP Grading      8012    ``zhixue.tools.grading_tools``
MCP Analysis     8013    ``zhixue.tools.analysis_tools``
===============  ======  ==================================

传输方式是 streamable HTTP，端点 ``/mcp``，与架构图上的 ``:8010/mcp`` 一致。
"""
