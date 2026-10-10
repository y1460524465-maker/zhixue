"""A2A 协议层。

架构图上"主应用 -> AgentNetwork -> 各 Agent"这一段走的是 A2A，
Agent 之间横向调用（读错题、写批改结果）也走 A2A。

实现策略：

* 装了 ``a2a-sdk`` 时，暴露标准的
  ``/.well-known/agent-card.json`` + JSON-RPC ``message/send``；
* 没装时自动退化为等价的 ``POST /task/send``，
  保证整个系统在当前环境也能端到端跑通。

两条路径的输入输出都是 :class:`zhixue.schemas.TaskRequest` / :class:`TaskResult`。
"""
