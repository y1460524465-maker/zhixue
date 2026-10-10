"""AgentNetwork —— 把 Router 的判定结果派发给对应的 Agent。

支持两种派发方式（对应 ``config.ini`` 的 ``zhixue.network_transport``）：

* ``a2a``   —— 通过 :class:`zhixue.a2a.client.A2AClient` 走真实 A2A 协议；
* ``local`` —— 进程内直接实例化 Agent，方便单进程调试。

一句话命中多个意图时会并发派发（``send_many``）。
"""

from __future__ import annotations

from typing import Any

from zhixue.a2a.client import A2AClient
from zhixue.config import get_settings
from zhixue.logging_setup import get_logger, set_task_id
from zhixue.registry import AGENT_DISPLAY_NAME, INTENT_TO_AGENT
from zhixue.schemas import Intent, RouterDecision, TaskRequest, TaskResult

logger = get_logger("app.network")


def local_agent(key: str):
    """进程内模式用：按需 import，避免无谓的模块加载。"""
    if key == "docgen":
        from zhixue.agents.docgen_agent import DocGenAgent

        return DocGenAgent(transport="local")
    if key == "question":
        from zhixue.agents.question_agent import QuestionAgent

        return QuestionAgent(transport="local")
    if key == "grading":
        from zhixue.agents.grading_agent import GradingAgent

        return GradingAgent(transport="local")
    if key == "analysis":
        from zhixue.agents.analysis_agent import AnalysisAgent

        return AnalysisAgent(transport="local")
    raise KeyError(f"未知 Agent: {key}")


class AgentNetwork:
    """主应用侧的调度中心。"""

    def __init__(self, client: A2AClient | None = None) -> None:
        self.settings = get_settings()
        self.client = client or A2AClient()

    @property
    def transport(self) -> str:
        return self.settings.network_transport

    # ------------------------------------------------------------------ #
    def plan(self, decision: RouterDecision) -> list[tuple[str, TaskRequest]]:
        """把意图拆成 ``(agent_key, TaskRequest)`` 列表。"""
        intents: list[Intent] = []
        for intent in [decision.intent, *decision.matched_intents]:
            if intent in INTENT_TO_AGENT and intent not in intents:
                intents.append(intent)
        if not intents:
            intents = [decision.intent]

        slots = dict(decision.slots)
        jobs: list[tuple[str, TaskRequest]] = []
        for intent in intents:
            agent = INTENT_TO_AGENT.get(intent)
            if not agent:
                continue
            jobs.append(
                (
                    agent,
                    TaskRequest(
                        session_id=str(slots.get("session_id") or ""),
                        intent=intent,
                        slots={**slots, "intent": intent.value},
                    ),
                )
            )
        return jobs

    # ------------------------------------------------------------------ #
    async def dispatch(self, decision: RouterDecision) -> list[TaskResult]:
        jobs = self.plan(decision)
        if not jobs:
            return []
        names = "、".join(AGENT_DISPLAY_NAME.get(agent, agent) for agent, _ in jobs)
        logger.info(
            "AgentNetwork 派发 %d 个任务 -> %s（通道：%s）", len(jobs), names, self.transport
        )

        if self.transport == "local":
            return await self._dispatch_local(jobs)
        return await self.client.send_many(jobs)

    async def _dispatch_local(self, jobs: list[tuple[str, TaskRequest]]) -> list[TaskResult]:
        """进程内串行执行（本地调试用；实现简单，日志清晰）。"""
        import asyncio

        def _run(agent: str, request: TaskRequest) -> TaskResult:
            set_task_id(request.task_id)
            return local_agent(agent).handle(request)

        loop = asyncio.get_running_loop()
        results: list[TaskResult] = []
        for agent, request in jobs:
            results.append(await loop.run_in_executor(None, _run, agent, request))
        return results

    # ------------------------------------------------------------------ #
    def status(self) -> list[dict[str, Any]]:
        """给前端展示各 Agent 的可用性。"""
        import httpx

        out: list[dict[str, Any]] = []
        for intent, agent in INTENT_TO_AGENT.items():
            url = self.settings.url(agent)
            entry: dict[str, Any] = {
                "agent": agent,
                "name": AGENT_DISPLAY_NAME.get(agent, agent),
                "intent": intent.value,
                "url": url,
                "online": False,
            }
            try:
                response = httpx.get(f"{url}/health", timeout=1.5)
                response.raise_for_status()
                entry.update(response.json())
                entry["online"] = True
            except Exception as exc:  # noqa: BLE001
                entry["error"] = str(exc)[:80]
            out.append(entry)
        return out


__all__ = ["AgentNetwork", "local_agent"]
