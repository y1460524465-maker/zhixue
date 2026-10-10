"""LLM Router —— 架构图左上角那个菱形判断框。

一次调用同时完成三件事：

1. **意图识别**：这句话要交给哪个 Agent（也可能同时命中多个）；
2. **槽位抽取**：从自然语言里抠出 student_id / homework_id / 知识点 等参数；
3. **缺信息判断**：对照 :data:`zhixue.schemas.REQUIRED_SLOTS`，
   缺什么就生成一句追问，流程回到"用户输入"。

多轮补槽：已收集的槽位存在 Redis 草稿里，下一句话会自动合并进来。
"""

from __future__ import annotations

import re
from typing import Any

from zhixue.config import get_settings
from zhixue.llm import LLMError, get_llm
from zhixue.logging_setup import get_logger
from zhixue.schemas import (
    REQUIRED_SLOTS,
    RouterDecision,
    Intent,
)
from zhixue.store import clear_draft, get_mysql, load_draft, save_draft

logger = get_logger("app.router")

INTENT_ALIASES: dict[str, Intent] = {
    "doc_gen": Intent.DOC_GEN,
    "document": Intent.DOC_GEN,
    "doc": Intent.DOC_GEN,
    "文档生成": Intent.DOC_GEN,
    "讲义": Intent.DOC_GEN,
    "学习计划": Intent.DOC_GEN,
    "question_gen": Intent.QUESTION_GEN,
    "question": Intent.QUESTION_GEN,
    "出题": Intent.QUESTION_GEN,
    "组卷": Intent.QUESTION_GEN,
    "试卷": Intent.QUESTION_GEN,
    "grading": Intent.GRADING,
    "批改": Intent.GRADING,
    "阅卷": Intent.GRADING,
    "analysis": Intent.ANALYSIS,
    "学情": Intent.ANALYSIS,
    "分析": Intent.ANALYSIS,
    "textbook_qa": Intent.TEXTBOOK_QA,
    "qa": Intent.TEXTBOOK_QA,
    "答疑": Intent.TEXTBOOK_QA,
    "chitchat": Intent.CHITCHAT,
    "闲聊": Intent.CHITCHAT,
}

#: 关键词兜底（LLM 不可用或返回异常时使用）
KEYWORD_INTENTS: list[tuple[Intent, tuple[str, ...]]] = [
    (Intent.GRADING, ("批改", "阅卷", "打分", "改卷", "答题卡", "作业批改")),
    (
        Intent.QUESTION_GEN,
        ("出题", "出几道", "出个题", "来几道", "道题", "组卷", "试卷", "练习题", "练练", "做题", "考一下", "考考"),
    ),
    (Intent.ANALYSIS, ("学情", "薄弱", "错题", "成绩", "掌握", "排名", "进步", "退步", "平均分")),
    (Intent.DOC_GEN, ("讲义", "学习计划", "复习计划", "生成文档", "整理成", "word", "文档")),
]

#: 明显是闲聊的短句，直接命中，不用走 LLM
CHITCHAT_RE = re.compile(
    r"^(你好|您好|hi|hello|嗨|哈喽|在吗|在不在|有人吗|你是谁|你叫什么|谢谢|多谢|感谢|再见|拜拜)[！!。~\s]*$",
    re.IGNORECASE,
)

#: 抽主题时要从句子里剥掉的模板词
_TOPIC_STOPWORDS = (
    "帮我", "请", "给我", "我想", "我要", "生成", "做一份", "做一份", "来一份", "写一份",
    "整理", "一份", "一下", "关于", "的", "，", ",", "。", "？", "?", "！", "!",
    "学习计划", "复习计划", "计划", "讲义", "文档", "word", "Word", "教案", "知识点",
)

#: 知识点名的拆分符，用于把"函数与装饰器"拆成"函数""装饰器"
_KP_SPLIT_RE = re.compile(r"[与和、·/]")

SLOT_HINTS = {
    "student_id": "学生学号",
    "homework_id": "作业编号",
    "knowledge_point": "知识点",
    "topic": "主题",
    "question": "具体问题",
    "file_path": "答题卡图片路径",
    "subject": "学科",
    "count": "题目数量",
    "q_type": "题型",
    "doc_type": "文档类型",
}


class LLMRouter:
    """意图识别 + 槽位填充。"""

    def __init__(self) -> None:
        self.settings = get_settings()

    # ------------------------------------------------------------------ #
    # 主入口
    # ------------------------------------------------------------------ #
    def route(
        self,
        message: str,
        session_id: str = "",
        student_id: str | None = None,
    ) -> RouterDecision:
        draft = load_draft(session_id) if session_id else {}
        draft_slots: dict[str, Any] = dict(draft.get("slots") or {})
        draft_intent = self._to_intent(draft.get("intent"))
        if student_id:
            draft_slots.setdefault("student_id", student_id)

        decision = self._classify(message, draft_slots, draft_intent)

        # 合并草稿：新一轮的信息优先
        merged: dict[str, Any] = {**draft_slots, **decision.slots}
        merged.setdefault("raw_input", message)
        if not merged.get("student_id") and student_id:
            merged["student_id"] = student_id
        decision.slots = merged

        required = REQUIRED_SLOTS.get(decision.intent, ())
        missing = [slot for slot in required if not merged.get(slot)]

        # 批改场景：有作业和学号就够了；如果什么都没给，还需要图片或作答
        if decision.intent is Intent.GRADING and not missing:
            if not merged.get("file_path") and not merged.get("student_answers"):
                missing = []  # 允许"重新批改"，由 Agent 自己复用库里记录

        decision.missing = missing
        if missing:
            decision.reply = self._ask_for(missing, decision, merged)

        if session_id:
            save_draft(session_id, {"slots": merged, "intent": decision.intent.value})
        logger.info(
            "路由结果 intent=%s missing=%s slots=%s",
            decision.intent.value,
            missing,
            list(merged.keys()),
        )
        return decision

    def reset(self, session_id: str) -> None:
        clear_draft(session_id)

    # ------------------------------------------------------------------ #
    # 意图识别
    # ------------------------------------------------------------------ #
    def _classify(
        self,
        message: str,
        draft_slots: dict[str, Any],
        draft_intent: Intent | None = None,
    ) -> RouterDecision:
        # 0) 明显是打招呼的短句，直接命中，省一次模型调用
        if CHITCHAT_RE.match((message or "").strip()):
            return RouterDecision(intent=Intent.CHITCHAT, confidence=0.99, slots={})
        try:
            return self._classify_with_llm(message, draft_slots)
        except LLMError as exc:
            logger.warning("Router 使用规则兜底（LLM 不可用：%s）", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Router 使用规则兜底（异常：%s）", exc)
        return self._classify_with_rules(message, draft_slots, draft_intent)

    def _classify_with_llm(
        self, message: str, draft_slots: dict[str, Any]
    ) -> RouterDecision:
        catalog = self._catalog()
        prompt = (
            "你是「智学」系统的意图路由器。请分析用户这句话，输出 JSON。\n\n"
            f"{catalog}\n\n"
            f"已收集的槽位：{draft_slots or '无'}\n"
            f"用户输入：{message}\n\n"
            "输出 JSON 格式：\n"
            '{"intent": "单个主意图", "matched_intents": ["可能命中的多个意图"], '
            '"confidence": 0.0~1.0, "slots": {"参数名": "参数值"}, '
            '"reply": "如果信息不全，这里写一句向用户的追问，否则留空"}\n'
            "只输出 JSON。"
        )
        payload = get_llm().chat_json(
            prompt,
            system="你是一个只输出 JSON 的意图识别器，不要输出解释或代码块。",
        )
        intent = self._to_intent(payload.get("intent"))
        matched = [
            i
            for i in (self._to_intent(x) for x in payload.get("matched_intents") or [])
            if i is not None
        ]
        slots = payload.get("slots") if isinstance(payload.get("slots"), dict) else {}
        try:
            confidence = float(payload.get("confidence", 0.6))
        except (TypeError, ValueError):
            confidence = 0.6
        return RouterDecision(
            intent=intent,
            matched_intents=sorted(set(matched), key=lambda i: i.value),
            confidence=max(0.0, min(1.0, confidence)),
            slots={k: v for k, v in slots.items() if v not in (None, "", [])},
            reply=str(payload.get("reply") or ""),
        )

    def _classify_with_rules(
        self,
        message: str,
        draft_slots: dict[str, Any],
        draft_intent: Intent | None = None,
    ) -> RouterDecision:
        text = message or ""
        matched: list[Intent] = []
        for intent, keywords in KEYWORD_INTENTS:
            if any(word in text for word in keywords):
                matched.append(intent)

        # 上一轮正在补槽时，"3 道题"/"S00001 和 HW00002"这种补充信息不该跳走
        if draft_intent and draft_intent not in matched:
            if not matched or self._looks_like_slot_filling(text):
                matched = [draft_intent]

        intent = matched[0] if matched else Intent.TEXTBOOK_QA
        slots = self._extract_slots(text)
        if intent is Intent.TEXTBOOK_QA and not slots.get("question"):
            slots["question"] = text
        return RouterDecision(
            intent=intent,
            matched_intents=matched,
            confidence=0.5,
            slots=slots,
        )

    @staticmethod
    def _looks_like_slot_filling(text: str) -> bool:
        """判断这句话是不是在补充上一轮的槽位（很短、且含编号/数量/学科）。"""
        if len(text) > 24:
            return False
        return bool(
            re.search(r"\bS\d{4,}\b|\bHW\d{4,}\b", text)
            or re.search(r"\d+\s*(道|个|题)", text)
            or re.search(r"^[^，。]{1,8}$", text)
        )

    @staticmethod
    def _to_intent(value: Any) -> Intent | None:
        if value is None:
            return None
        text = str(value).strip().lower()
        if text in INTENT_ALIASES:
            return INTENT_ALIASES[text]
        for alias, intent in INTENT_ALIASES.items():
            if alias in text:
                return intent
        return None

    # ------------------------------------------------------------------ #
    # 槽位抽取（规则兜底用）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_slots(text: str) -> dict[str, Any]:
        slots: dict[str, Any] = {}
        student = re.search(r"\bS\d{4,}\b", text)
        if student:
            slots["student_id"] = student.group(0)
        homework = re.search(r"\bHW\d{4,}\b", text)
        if homework:
            slots["homework_id"] = homework.group(0)
        path = re.search(r"[A-Za-z]:\\[^\s\"']+|/[\w./-]+\.(?:png|jpg|jpeg|docx|txt)", text)
        if path:
            slots["file_path"] = path.group(0)
        count = re.search(r"(\d+)\s*(?:道|个|题)", text)
        if count:
            slots["count"] = int(count.group(1))
        for subject in ("Python", "Java", "前端", "大数据", "软件测试"):
            if subject.lower() in text.lower():
                slots["subject"] = subject
                break
        # 实体识别：用知识点表反查句子里提到的知识点
        entity = _match_knowledge_point(text)
        if entity:
            slots["knowledge_point"] = entity["name"]
            slots["topic"] = entity["name"]
            slots["kp_id"] = entity["kp_id"]
            slots.setdefault("subject", entity["subject"])
        for doc_type, words in {
            "study_plan": ("学习计划", "复习计划", "计划"),
            "lecture": ("讲义", "知识点", "讲解"),
        }.items():
            if any(word in text for word in words):
                slots["doc_type"] = doc_type
                break
        # 主题兜底：剥掉模板词后剩下的就是主题
        if "topic" not in slots and slots.get("doc_type"):
            topic = _strip_template_words(text)
            if topic:
                slots["topic"] = topic
        if "knowledge_point" not in slots and "道题" in text:
            topic = _strip_template_words(text)
            if topic:
                slots["knowledge_point"] = topic
        return slots

    # ------------------------------------------------------------------ #
    # 追问
    # ------------------------------------------------------------------ #
    @staticmethod
    def _ask_for(missing: list[str], decision: RouterDecision, slots: dict[str, Any]) -> str:
        labels = "、".join(SLOT_HINTS.get(slot, slot) for slot in missing)
        if decision.intent is Intent.DOC_GEN and "topic" in missing:
            return "好的，我来帮你生成文档。请告诉我具体想讲哪个知识点或主题？"
        if decision.intent is Intent.QUESTION_GEN and "knowledge_point" in missing:
            return "没问题，我来出题。请告诉我出哪个知识点（也可以顺便说明数量和题型）？"
        if decision.intent is Intent.GRADING:
            if "student_id" in missing and "homework_id" in missing:
                return "我来帮你批改。请提供学生学号（如 S00001）和作业编号（如 HW00001）。"
            if "student_id" in missing:
                return "请提供学生学号（如 S00001）。"
            if "homework_id" in missing:
                return "请提供作业编号（如 HW00001）。"
        if decision.intent is Intent.ANALYSIS and "student_id" in missing:
            return "我来帮你看学情。请提供学生学号（如 S00001）。"
        return f"还需要补充这些信息才能继续：{labels}。"

    # ------------------------------------------------------------------ #
    # 提示词素材
    # ------------------------------------------------------------------ #
    @staticmethod
    def _catalog() -> str:
        return (
            "可用意图：\n"
            "- doc_gen：生成文档（讲义、学习计划、错题报告、试卷排版）。"
            "必填槽位 topic（主题），可选 subject / doc_type / student_name。\n"
            "- question_gen：出题 / 组卷。必填槽位 knowledge_point（知识点），"
            "可选 count / q_type / subject / difficulty / mode(homework|exam)。\n"
            "- grading：作业批改。必填槽位 student_id、homework_id，"
            "可选 file_path（答题卡图片）。\n"
            "- analysis：学情分析。必填槽位 student_id，可选 question（具体统计需求）。\n"
            "- textbook_qa：课本知识答疑。必填槽位 question。\n"
            "- chitchat：打招呼、道谢、问你是谁。\n"
        )

    # ------------------------------------------------------------------ #
    # 学生上下文
    # ------------------------------------------------------------------ #
    @staticmethod
    def list_students() -> list[dict[str, Any]]:
        try:
            return [
                dict(r)
                for r in get_mysql().query(
                    "SELECT student_id, name, class_name FROM student ORDER BY student_id"
                )
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取学生列表失败: %s", exc)
            return []


def _strip_template_words(text: str) -> str:
    """把"生成装饰器的学习计划"这类句子里的模板词剥掉，留下主题词。"""
    result = text or ""
    for word in _TOPIC_STOPWORDS:
        result = result.replace(word, " ")
    result = re.sub(r"\d+", " ", result)
    result = re.sub(r"\s+", " ", result).strip(" 的了吗呢吧啊")
    return result.strip()


_KP_CACHE: dict[str, Any] = {"rows": None, "loaded_at": 0.0}
_KP_TTL = 300.0


def _knowledge_points() -> list[dict[str, Any]]:
    """知识点表很小（当前 19 条），带 5 分钟缓存读一次就够。"""
    import time as _time

    now = _time.time()
    if _KP_CACHE["rows"] is None or now - _KP_CACHE["loaded_at"] > _KP_TTL:
        try:
            rows = [
                dict(r)
                for r in get_mysql().query("SELECT kp_id, subject, name FROM knowledge_point")
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取知识点表失败: %s", exc)
            rows = []
        _KP_CACHE["rows"] = rows
        _KP_CACHE["loaded_at"] = now
    return _KP_CACHE["rows"] or []


def _match_knowledge_point(text: str) -> dict[str, Any] | None:
    """句子 -> 知识点。用已知知识点做反向匹配，比纯正则稳得多。"""
    if not text:
        return None
    lowered = text.lower()
    best: tuple[int, dict[str, Any]] | None = None
    for row in _knowledge_points():
        for token in [row["name"], *_KP_SPLIT_RE.split(row["name"])]:
            token = (token or "").strip()
            if len(token) < 2 or token.lower() not in lowered:
                continue
            if best is None or len(token) > best[0]:
                best = (len(token), row)
    return best[1] if best else None


def match_knowledge_point(text: str) -> dict[str, Any] | None:
    """对外的实体识别入口（主应用答疑时也用得上）。"""
    return _match_knowledge_point(text)


__all__ = [
    "LLMRouter",
    "INTENT_ALIASES",
    "KEYWORD_INTENTS",
    "CHITCHAT_RE",
    "match_knowledge_point",
]
