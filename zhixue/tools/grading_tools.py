"""作业批改 Agent 的工具集（对应架构图 MCP Grading :8012/mcp）。

* ``ocr_extract``     -> OCR 识别（答题卡图片 -> 结构化作答）
* ``compare_answer``  -> 答案比对（客观题规则匹配 + 主观题 LLM 评分）
* ``grade_submission``-> 一次完整批改并落库
* ``sync_mistake_records`` -> 把错题同步进错题记录库
  （架构图上这一步是学情分析 Agent 干的，所以单独拆出来给它调用）
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from zhixue.config import get_settings
from zhixue.logging_setup import get_logger
from zhixue.store import get_mysql

logger = get_logger("tools.grading")

OPTION_RE = re.compile(r"^[A-Za-z]$")
NUMBERED_RE = re.compile(r"^\s*(\d+)\s*[.、]\s*(.*)$")
ANSWER_RE = re.compile(r"^\s*(?:作答|答案|答)\s*[:：]\s*(.*)$")


# --------------------------------------------------------------------------- #
# OCR
# --------------------------------------------------------------------------- #
_OCR_ENGINE: Any = None
_OCR_FAILED = False


def _get_ocr() -> Any:
    """懒加载 OCR 引擎（优先 GPU 版，其次 CPU 版）。"""
    global _OCR_ENGINE, _OCR_FAILED
    if _OCR_ENGINE is not None or _OCR_FAILED:
        return _OCR_ENGINE
    try:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
        logger.info("RapidOCR(onnxruntime) 加载完成")
    except Exception as exc:
        _OCR_FAILED = True
        logger.warning("OCR 引擎不可用: %s", exc)
    return _OCR_ENGINE


def parse_answer_sheet(lines: list[str]) -> dict[str, str]:
    """把答题卡的文本行解析成 ``{题号: 作答}``。"""
    answers: dict[str, str] = {}
    current: str | None = None
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        match = ANSWER_RE.match(line)
        if match and current:
            answers[current] = match.group(1).strip()
            continue
        numbered = NUMBERED_RE.match(line)
        if numbered:
            current = numbered.group(1)
            rest = numbered.group(2).strip()
            # 形如 "1. B" 的短行直接当答案
            if rest and len(rest) <= 6 and not rest.startswith("题目"):
                answers[current] = rest
            continue
        if current and current in answers:
            answers[current] += line
    return answers


def ocr_extract(file_path: str) -> dict[str, Any]:
    """识别一张答题卡图片，返回原文和结构化作答。"""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    started = time.time()
    engine = _get_ocr()
    lines: list[str] = []
    if engine is not None:
        try:
            result, _ = engine(str(path))
            lines = [item[1] for item in (result or []) if len(item) > 1]
        except Exception as exc:
            logger.warning("OCR 识别失败: %s", exc)

    if not lines:
        # 没有 OCR 引擎时的兜底：文件本身就是文本（比如 .txt 或已转好的 .md）
        for suffix in (".txt", ".md"):
            alt = path.with_suffix(suffix)
            if alt.exists():
                lines = alt.read_text(encoding="utf-8").splitlines()
                break

    answers = parse_answer_sheet(lines)
    elapsed = time.time() - started
    logger.info("OCR 完成 %s: %d 行 / %d 题 (%.2fs)", path.name, len(lines), len(answers), elapsed)
    return {
        "file": str(path),
        "text": "\n".join(lines),
        "lines": lines,
        "answers": answers,
        "ocr_available": engine is not None,
        "elapsed": round(elapsed, 2),
    }


# --------------------------------------------------------------------------- #
# 答案比对
# --------------------------------------------------------------------------- #
def _normalize(text: str) -> str:
    return re.sub(r"[\s，。；、,.;:：'\"“”‘’()（）]+", "", str(text or "")).lower()


def _keyword_overlap(student: str, standard: str) -> float:
    from zhixue.vector import tokenize

    a = set(tokenize(student))
    b = set(tokenize(standard))
    if not b:
        return 0.0
    return len(a & b) / len(b)


def _llm_score(student_answer: str, std_answer: str, stem: str, rubric: str) -> tuple[float, str] | None:
    """让模型给主观题打分，返回 (0~1 的比例, 评语)。失败返回 None。"""
    from zhixue.llm import LLMClient, LLMError

    prompt = (
        "你是严谨的阅卷老师。请对照参考答案给学生作答打分。\n"
        f"【题目】{stem}\n"
        f"【参考答案】{std_answer}\n"
        f"【评分要点】{rubric or '无'}\n"
        f"【学生作答】{student_answer}\n\n"
        "只输出 JSON：{\"ratio\": 0~1 之间的小数, \"comment\": \"不超过 40 字的评语\"}"
    )
    try:
        payload = LLMClient().chat_json(prompt, fallback={})
    except LLMError as exc:
        logger.warning("LLM 评分失败: %s", exc)
        return None
    if not payload:
        return None
    try:
        ratio = max(0.0, min(1.0, float(payload.get("ratio", 0))))
    except (TypeError, ValueError):
        return None
    return ratio, str(payload.get("comment", ""))[:80]


def compare_answer(
    student_answer: str,
    std_answer: str,
    q_type: str = "简答",
    stem: str = "",
    rubric: str = "",
    use_llm: bool = True,
) -> dict[str, Any]:
    """比对一道题，返回 ``{ratio, is_correct, comment, method}``。"""
    student = str(student_answer or "").strip()
    standard = str(std_answer or "").strip()

    if not student:
        return {"ratio": 0.0, "is_correct": False, "comment": "未作答。", "method": "rule"}

    # 客观题：字母/判断，直接规范化比较
    if q_type in ("单选", "多选", "判断", "填空"):
        if _normalize(student) == _normalize(standard):
            return {"ratio": 1.0, "is_correct": True, "comment": "回答正确。", "method": "rule"}
        if q_type in ("单选", "判断"):
            return {
                "ratio": 0.0,
                "is_correct": False,
                "comment": f"答案应为 {standard}。",
                "method": "rule",
            }

    # 主观题：先看关键词覆盖，再让模型复核
    overlap = _keyword_overlap(student, standard)
    if use_llm:
        scored = _llm_score(student, standard, stem, rubric)
        if scored is not None:
            ratio, comment = scored
            return {
                "ratio": round(ratio, 3),
                "is_correct": ratio >= 0.8,
                "comment": comment or ("要点覆盖较好。" if ratio >= 0.8 else "要点有遗漏。"),
                "method": "llm",
            }

    ratio = round(min(overlap * 1.2, 1.0), 3)
    return {
        "ratio": ratio,
        "is_correct": ratio >= 0.8,
        "comment": "关键词覆盖率 %.0f%%。" % (overlap * 100),
        "method": "keyword",
    }


# --------------------------------------------------------------------------- #
# 批改主流程
# --------------------------------------------------------------------------- #
def get_homework(homework_id: str) -> dict[str, Any]:
    mysql = get_mysql()
    homework = mysql.query_one("SELECT * FROM homework WHERE homework_id = %s", (homework_id,))
    if not homework:
        raise ValueError(f"作业不存在: {homework_id}")
    questions = mysql.query(
        "SELECT q.q_id, q.subject, q.kp_id, q.q_type, q.difficulty, q.stem, q.options, "
        "       q.answer AS std_answer, q.analysis, hq.seq, hq.score AS full_score, "
        "       ha.rubric "
        "FROM homework_question hq "
        "JOIN question_bank q ON q.q_id = hq.q_id "
        "LEFT JOIN homework_answer ha ON ha.homework_id = hq.homework_id AND ha.q_id = hq.q_id "
        "WHERE hq.homework_id = %s ORDER BY hq.seq",
        (homework_id,),
    )
    homework["questions"] = [dict(q) for q in questions]
    return dict(homework)


def list_student_answers(
    homework_id: str, student_id: str, limit: int = 5
) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in get_mysql().query(
            "SELECT * FROM grading_result WHERE homework_id = %s AND student_id = %s "
            "ORDER BY q_id LIMIT %s",
            (homework_id, student_id, limit),
        )
    ]


def grade_submission(
    homework_id: str,
    student_id: str,
    file_path: str | None = None,
    student_answers: dict[str, str] | None = None,
    use_llm: bool = True,
    write_back: bool = True,
) -> dict[str, Any]:
    """批改一次作业并落库。

    :param file_path: 答题卡图片，给了就先用 OCR 识别
    :param student_answers: 也可以直接给 ``{题号: 作答}``（题号是 1-based 的序号）
    """
    started = time.time()
    mysql = get_mysql()
    homework = get_homework(homework_id)
    questions = homework["questions"]
    if not questions:
        raise ValueError(f"作业 {homework_id} 没有配置题目")

    ocr_result: dict[str, Any] | None = None
    answers: dict[str, str] = dict(student_answers or {})
    if file_path:
        ocr_result = ocr_extract(file_path)
        for seq, text in ocr_result["answers"].items():
            answers.setdefault(seq, text)

    details: list[dict[str, Any]] = []
    total = 0.0
    full = 0.0
    kp_bucket: dict[str, dict[str, float]] = {}

    for index, question in enumerate(questions, start=1):
        seq = str(index)
        student_answer = answers.get(seq) or answers.get(question["q_id"]) or ""
        comparison = compare_answer(
            student_answer,
            question["std_answer"],
            q_type=question["q_type"],
            stem=question["stem"],
            rubric=question.get("rubric") or "",
            use_llm=use_llm,
        )
        score = round(float(question["full_score"]) * comparison["ratio"], 1)
        total += score
        full += float(question["full_score"])
        bucket = kp_bucket.setdefault(question["kp_id"], {"score": 0.0, "full": 0.0})
        bucket["score"] += score
        bucket["full"] += float(question["full_score"])
        details.append(
            {
                "seq": index,
                "q_id": question["q_id"],
                "kp_id": question["kp_id"],
                "q_type": question["q_type"],
                "stem": question["stem"],
                "student_answer": student_answer,
                "std_answer": question["std_answer"],
                "score": score,
                "full_score": float(question["full_score"]),
                "is_correct": comparison["is_correct"],
                "comment": comparison["comment"],
                "method": comparison["method"],
            }
        )

    report = {
        "homework_id": homework_id,
        "homework_title": homework["title"],
        "subject": homework["subject"],
        "student_id": student_id,
        "score": round(total, 1),
        "full_score": round(full, 1),
        "rate": round(total / full, 3) if full else 0.0,
        "kp_scores": {
            kp: round(v["score"] / v["full"], 3) for kp, v in kp_bucket.items() if v["full"]
        },
        "details": details,
        "ocr": {
            "used": ocr_result is not None,
            "available": bool(ocr_result and ocr_result.get("ocr_available")),
            "recognized": len(ocr_result["answers"]) if ocr_result else 0,
        },
        "elapsed": round(time.time() - started, 2),
    }

    if write_back:
        report["submission_id"] = _persist_grading(homework, report, file_path)
    return report


def _persist_grading(homework: dict[str, Any], report: dict[str, Any], file_path: str | None) -> str:
    """写入 submission / grading_result / score_record 三张表。"""
    mysql = get_mysql()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    submission_id = "SUB" + uuid.uuid4().hex[:12].upper()

    existing = mysql.query_one(
        "SELECT submission_id FROM submission WHERE homework_id = %s AND student_id = %s",
        (report["homework_id"], report["student_id"]),
    )
    if existing:
        submission_id = existing["submission_id"]
        mysql.execute(
            "UPDATE submission SET submit_time = %s, file_path = COALESCE(%s, file_path), status = 'graded' "
            "WHERE submission_id = %s",
            (now, file_path, submission_id),
        )
        mysql.execute("DELETE FROM grading_result WHERE submission_id = %s", (submission_id,))
        mysql.execute("DELETE FROM score_record WHERE student_id = %s AND homework_id = %s",
                      (report["student_id"], report["homework_id"]))
    else:
        mysql.execute(
            "INSERT INTO submission (submission_id, homework_id, student_id, submit_time, file_path, status) "
            "VALUES (%s, %s, %s, %s, %s, 'graded')",
            (submission_id, report["homework_id"], report["student_id"], now, file_path),
        )

    mysql.execute_many(
        "INSERT INTO grading_result "
        "(grade_id, submission_id, student_id, homework_id, q_id, student_answer, std_answer, "
        " is_correct, score, full_score, comment, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        [
            (
                "G" + uuid.uuid4().hex[:12].upper(), submission_id, report["student_id"],
                report["homework_id"], d["q_id"], d["student_answer"], d["std_answer"],
                int(d["is_correct"]), d["score"], d["full_score"], d["comment"], now,
            )
            for d in report["details"]
        ],
    )
    import json as _json

    mysql.execute(
        "INSERT INTO score_record "
        "(score_id, student_id, homework_id, subject, score, full_score, submit_time, kp_scores) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            "SC" + uuid.uuid4().hex[:12].upper(), report["student_id"], report["homework_id"],
            report["subject"], report["score"], report["full_score"], now,
            _json.dumps(report["kp_scores"], ensure_ascii=False),
        ),
    )
    logger.info(
        "批改落库: %s / %s -> %.1f/%.1f",
        report["homework_id"], report["student_id"], report["score"], report["full_score"],
    )
    return submission_id


def sync_mistake_records(
    student_id: str, homework_id: str | None = None
) -> dict[str, Any]:
    """把批改结果里的错题同步到错题记录库。

    架构图上这一步由学情分析 Agent 通过 A2AClient 触发，所以单独抽成工具。
    """
    mysql = get_mysql()
    sql = (
        "SELECT g.q_id, g.homework_id, q.kp_id, q.subject, g.score, g.full_score, g.created_at "
        "FROM grading_result g JOIN question_bank q ON q.q_id = g.q_id "
        "WHERE g.student_id = %s AND g.is_correct = 0"
    )
    params: list[Any] = [student_id]
    if homework_id:
        sql += " AND g.homework_id = %s"
        params.append(homework_id)
    rows = [dict(r) for r in mysql.query(sql, tuple(params))]

    upserted = 0
    for row in rows:
        mastery = round(float(row["score"]) / float(row["full_score"] or 1), 3)
        mysql.execute(
            "INSERT INTO mistake_record "
            "(mistake_id, student_id, q_id, kp_id, subject, wrong_count, last_wrong_time, mastery) "
            "VALUES (%s, %s, %s, %s, %s, 1, %s, %s) "
            "ON DUPLICATE KEY UPDATE wrong_count = wrong_count + 1, "
            "last_wrong_time = VALUES(last_wrong_time), mastery = VALUES(mastery)",
            (
                "M" + uuid.uuid4().hex[:12].upper(), student_id, row["q_id"], row["kp_id"],
                row["subject"], row["created_at"], mastery,
            ),
        )
        upserted += 1
    logger.info("同步错题 %s: %d 条", student_id, upserted)
    return {"student_id": student_id, "homework_id": homework_id, "mistakes": upserted}


__all__ = [
    "ocr_extract",
    "parse_answer_sheet",
    "compare_answer",
    "get_homework",
    "list_student_answers",
    "grade_submission",
    "sync_mistake_records",
]
