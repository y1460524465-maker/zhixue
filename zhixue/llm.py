"""大模型访问层。

统一走 DashScope 的 OpenAI 兼容接口，提供三种用法：

* :meth:`LLMClient.chat`      —— 普通问答
* :meth:`LLMClient.chat_json` —— 强制结构化输出（Router 用它）
* :meth:`LLMClient.stream`    —— 流式输出（前端打字机效果）
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

from zhixue.config import Settings, get_settings
from zhixue.logging_setup import get_logger

logger = get_logger("llm")

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class LLMError(RuntimeError):
    """模型调用失败。"""


class LLMClient:
    """薄封装；线程安全（openai 客户端本身是）。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: Any = None
        # 熔断：Key 一旦被判定无效，后续调用直接失败返回，
        # 避免每个 Agent 都白等一次网络超时。
        self._auth_failed = False

    @property
    def client(self) -> Any:
        if self._client is None:
            if not self.settings.llm_api_key:
                raise LLMError(
                    "缺少 API Key：请在 config.ini 的 [llm] 段填 dashscope_api_key，"
                    "或设置环境变量 DASHSCOPE_API_KEY"
                )
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.settings.llm_api_key,
                base_url=self.settings.llm_base_url,
                timeout=self.settings.llm_timeout,
            )
        return self._client

    # -- 基础调用 ---------------------------------------------------------- #
    def chat(
        self,
        prompt: str,
        system: str = "你是「智学」智慧教学系统的助手，回答务必准确、简洁、面向学生。",
        temperature: float = 0.3,
    ) -> str:
        if self._auth_failed:
            raise LLMError("API Key 无效，已跳过模型调用（请在 config.ini 的 [llm] 段更新 dashscope_api_key）")
        try:
            resp = self.client.chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
            )
        except LLMError:
            raise
        except Exception as exc:
            self._note_failure(exc)
            logger.error("LLM 调用失败: %s", exc)
            raise LLMError(str(exc)) from exc
        return (resp.choices[0].message.content or "").strip()

    def _note_failure(self, exc: Exception) -> None:
        text = str(exc)
        if "401" in text or "invalid_api_key" in text or "Incorrect API key" in text:
            if not self._auth_failed:
                logger.error("检测到 API Key 无效，本次进程内不再尝试调用模型")
            self._auth_failed = True

    def stream(
        self,
        prompt: str,
        system: str = "你是「智学」智慧教学系统的助手，回答务必准确、简洁、面向学生。",
        temperature: float = 0.3,
    ) -> Iterator[str]:
        if self._auth_failed:
            raise LLMError("API Key 无效，已跳过模型调用")
        try:
            completion = self.client.chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                stream=True,
            )
            for chunk in completion:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except LLMError:
            raise
        except Exception as exc:  # pragma: no cover - 依赖外部服务
            self._note_failure(exc)
            logger.error("LLM 流式调用失败: %s", exc)
            raise LLMError(str(exc)) from exc

    def chat_json(
        self,
        prompt: str,
        system: str = "你是一个只输出 JSON 的严格接口，不要输出任何解释文字或 Markdown 代码块。",
        temperature: float = 0.0,
        fallback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """要求模型输出 JSON，并容错解析。"""
        try:
            raw = self.chat(prompt, system=system, temperature=temperature)
        except LLMError:
            if fallback is not None:
                logger.warning("chat_json 调用失败，使用兜底结果")
                return fallback
            raise
        parsed = extract_json(raw)
        if parsed is None:
            logger.warning("模型输出不是合法 JSON，原文: %s", raw[:200])
            if fallback is not None:
                return fallback
            raise LLMError(f"模型未返回合法 JSON: {raw[:200]}")
        return parsed


def extract_json(text: str) -> dict[str, Any] | None:
    """从模型输出里抠出第一个 JSON 对象。"""
    if not text:
        return None
    text = text.strip()
    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except ValueError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
        return value if isinstance(value, dict) else None
    except ValueError:
        return None


_llm: LLMClient | None = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm


__all__ = ["LLMClient", "LLMError", "get_llm", "extract_json"]
