"""出题 Agent 的工具集（对应架构图 MCP Question :8011/mcp）。

* ``search_question_bank`` -> RAG 题库检索（题目向量库）
* ``select_questions``     -> 按知识点/题型/难度结构化选题
* ``create_homework``      -> 把选好的题落成一份作业
* ``build_exam_doc``       -> 渲染试卷 Word（复用模板库的 exam_paper 模板）
"""

from __future__ import annotations

import json
import random
import time
from datetime import datetime
from typing import Any

from zhixue.config import get_settings
from zhixue.logging_setup import get_logger
from zhixue.store import get_mysql
from zhixue.tools.docgen_tools import render_word
from zhixue.vector import get_retriever

logger = get_logger("tools.question")


def list_knowledge_points(subject: str | None = None) -> list[dict[str, Any]]:
    """知识点清单。"""
    sql = "SELECT kp_id, subject, name, difficulty, description FROM knowledge_point"
    params: tuple[Any, ...] = ()
    if subject:
        sql += " WHERE subject = %s"
        params = (subject,)
    sql += " ORDER BY kp_id"
    return [dict(r) for r in get_mysql().query(sql, params)]


def resolve_knowledge_point(knowledge_point: str, subject: str | None = None) -> dict[str, Any] | None:
    """把自由文本（"装饰器"、"KP-PY-01"）解析成知识点记录。"""
    mysql = get_mysql()
    row = mysql.query_one("SELECT * FROM knowledge_point WHERE kp_id = %s", (knowledge_point,))
    if row:
        return dict(row)

    sql = (
        "SELECT * FROM knowledge_point WHERE name LIKE %s OR description LIKE %s"
    )
    params: list[Any] = [f"%{knowledge_point}%", f"%{knowledge_point}%"]
    if subject:
        sql += " AND subject = %s"
        params.append(subject)
    sql += " ORDER BY difficulty LIMIT 1"
    row = mysql.query_one(sql, tuple(params))
    if row:
        return dict(row)

    # 最后用检索兜底：拿最相关的一段课本找到它对应的知识点
    hits = get_retriever().search_textbook(knowledge_point, k=1, subject=subject)
    if hits and hits[0].get("kp_id"):
        row = mysql.query_one("SELECT * FROM knowledge_point WHERE kp_id = %s", (hits[0]["kp_id"],))
        if row:
            return dict(row)
    return None


def search_question_bank(
    query: str, subject: str | None = None, k: int | None = None
) -> list[dict[str, Any]]:
    """在题目向量库里做语义检索。"""
    settings = get_settings()
    k = k or settings.retrieval_k
    hits = get_retriever().search_questions(query, k=k, subject=subject or None)
    logger.info("题库检索 '%s' -> %d 条", query, len(hits))
    results: list[dict[str, Any]] = []
    for hit in hits:
        row = hit.get("_row")
        if not row:
            row = get_mysql().query_one("SELECT * FROM question_bank WHERE q_id = %s", (hit.get("id"),))
        if not row:
            continue
        results.append(_format_question(row, score=hit.get("score", 0.0), backend=hit.get("backend", "")))
    return results


def _format_question(row: dict[str, Any], score: float = 0.0, backend: str = "") -> dict[str, Any]:
    options = row.get("options")
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except ValueError:
            options = []
    return {
        "q_id": row["q_id"],
        "subject": row["subject"],
        "kp_id": row["kp_id"],
        "q_type": row["q_type"],
        "difficulty": row["difficulty"],
        "stem": row["stem"],
        "options": options or [],
        "answer": row["answer"],
        "analysis": row.get("analysis") or "",
        "score": round(float(score), 4),
        "backend": backend,
    }


def select_questions(
    kp_id: str | None = None,
    subject: str | None = None,
    q_type: str | None = None,
    difficulty: int | None = None,
    n: int = 5,
    shuffle: bool = False,
) -> list[dict[str, Any]]:
    """结构化选题（出题的核心）。"""
    sql = "SELECT * FROM question_bank WHERE 1=1"
    params: list[Any] = []
    if kp_id:
        sql += " AND kp_id = %s"
        params.append(kp_id)
    if subject:
        sql += " AND subject = %s"
        params.append(subject)
    if q_type:
        sql += " AND q_type = %s"
        params.append(q_type)
    if difficulty:
        sql += " AND difficulty = %s"
        params.append(difficulty)
    rows = [dict(r) for r in get_mysql().query(sql, tuple(params))]
    if shuffle:
        random.shuffle(rows)
    else:
        rows.sort(key=lambda r: (r["difficulty"], r["q_id"]))
    logger.info("结构化选题 kp=%s subject=%s -> %d 道", kp_id, subject, min(len(rows), n))
    return [_format_question(r) for r in rows[:n]]


def _next_homework_id() -> str:
    row = get_mysql().query_one("SELECT MAX(homework_id) AS m FROM homework")
    current = (row or {}).get("m") or "HW00000"
    try:
        seq = int(str(current)[2:]) + 1
    except ValueError:
        seq = 1
    return f"HW{seq:05d}"


def create_homework(
    title: str,
    question_ids: list[str],
    subject: str | None = None,
    kp_id: str | None = None,
    score_per_question: int = 20,
    due_days: int = 7,
) -> dict[str, Any]:
    """把选中的题目落成一份新作业（写进作业库 + 作业答案库）。"""
    mysql = get_mysql()
    if not question_ids:
        raise ValueError("question_ids 不能为空")

    placeholders = ", ".join(["%s"] * len(question_ids))
    rows = mysql.query(
        f"SELECT q_id, subject, kp_id, answer, analysis FROM question_bank WHERE q_id IN ({placeholders})",
        tuple(question_ids),
    )
    if not rows:
        raise ValueError("未找到任何题目")

    homework_id = _next_homework_id()
    subject = subject or rows[0]["subject"]
    kp_id = kp_id or rows[0]["kp_id"]
    full_score = score_per_question * len(rows)
    now = datetime.now()
    due = (now.replace(hour=23, minute=59, second=0, microsecond=0)).strftime("%Y-%m-%d")

    mysql.execute(
        "INSERT INTO homework (homework_id, title, subject, kp_id, full_score, publish_time, due_date) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (homework_id, title, subject, kp_id, full_score, now.strftime("%Y-%m-%d %H:%M:%S"), due),
    )
    order = {qid: index for index, qid in enumerate(question_ids)}
    rows.sort(key=lambda r: order.get(r["q_id"], 999))
    mysql.execute_many(
        "INSERT INTO homework_question (homework_id, q_id, seq, score) VALUES (%s, %s, %s, %s)",
        [(homework_id, r["q_id"], i + 1, score_per_question) for i, r in enumerate(rows)],
    )
    mysql.execute_many(
        "INSERT INTO homework_answer (homework_id, q_id, std_answer, rubric) VALUES (%s, %s, %s, %s)",
        [(homework_id, r["q_id"], r["answer"], r.get("analysis") or "") for r in rows],
    )
    logger.info("新建作业 %s，共 %d 题", homework_id, len(rows))
    return {
        "homework_id": homework_id,
        "title": title,
        "subject": subject,
        "kp_id": kp_id,
        "question_count": len(rows),
        "full_score": full_score,
        "due_date": due,
    }


def build_exam_doc(
    title: str,
    questions: list[dict[str, Any]],
    subject: str = "",
    full_score: int | None = None,
    duration: int = 60,
    with_answers: bool = True,
    subdir: str | None = None,
) -> dict[str, Any]:
    """把题目渲染成一份试卷 Word。"""
    lines: list[str] = []
    answers: list[str] = []
    for index, item in enumerate(questions, start=1):
        lines.append(f"{index}. [{item.get('q_type', '')}] {item.get('stem', '')}")
        for option in item.get("options") or []:
            lines.append(f"    {option}")
        if item.get("q_type") in ("简答", "编程"):
            lines.append("    " + "_" * 46)
        lines.append("")
        answers.append(f"{index}. {item.get('answer', '')}")

    data = {
        "title": title,
        "subject": subject or (questions[0].get("subject", "") if questions else ""),
        "full_score": full_score if full_score is not None else 20 * len(questions),
        "duration": duration,
        "questions": "\n".join(lines),
        "answers": "\n".join(answers) if with_answers else "（略）",
    }
    result = render_word(
        "exam_paper", data, output_name=f"exam_{int(time.time())}.docx", subdir=subdir
    )
    result["question_count"] = len(questions)
    return result


def build_exam_from_ids(
    title: str,
    question_ids: list[str],
    subject: str = "",
    duration: int = 60,
    with_answers: bool = True,
    subdir: str | None = None,
) -> dict[str, Any]:
    """按题号出卷（MCP 工具用这个版本，避免传大块 JSON）。"""
    questions: list[dict[str, Any]] = []
    mysql = get_mysql()
    for q_id in question_ids:
        row = mysql.query_one("SELECT * FROM question_bank WHERE q_id = %s", (q_id,))
        if row:
            questions.append(_format_question(row))
    if not questions:
        raise ValueError("未找到任何题目")
    return build_exam_doc(
        title, questions, subject=subject, duration=duration, with_answers=with_answers,
        subdir=subdir,
    )


# --------------------------------------------------------------------------- #
# 指针 -> 实体
# --------------------------------------------------------------------------- #
def get_questions_by_ids(question_ids: list[str]) -> list[dict[str, Any]]:
    """按题目编号批量取题（错题记录里存的是编号，题干要回题库换）。"""
    if not question_ids:
        return []
    placeholders = ", ".join(["%s"] * len(question_ids))
    rows = get_mysql().query(
        f"SELECT * FROM question_bank WHERE q_id IN ({placeholders})", tuple(question_ids)
    )
    order = {qid: index for index, qid in enumerate(question_ids)}
    result = [_format_question(dict(r)) for r in rows]
    result.sort(key=lambda q: order.get(q["q_id"], 999))
    return result


# --------------------------------------------------------------------------- #
# 交互记忆：出过什么题，避免重复
# --------------------------------------------------------------------------- #
def record_issued_questions(
    student_id: str,
    question_ids: list[str],
    homework_id: str | None = None,
    source: str = "homework",
) -> int:
    """记下"这套题发给过这个学生"，供下次出题时排除。"""
    if not student_id or not question_ids:
        return 0
    import uuid as _uuid
    from datetime import datetime as _dt

    now = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        ("H" + _uuid.uuid4().hex[:12].upper(), student_id, q_id, homework_id, source, now)
        for q_id in question_ids
    ]
    get_mysql().execute_many(
        "INSERT INTO question_history (history_id, student_id, q_id, homework_id, source, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        rows,
    )
    logger.info("记录出题历史 %s: %d 条 (%s)", student_id, len(rows), source)
    return len(rows)


def recently_issued_q_ids(student_id: str, days: int = 30, limit: int = 500) -> list[str]:
    """最近若干天已经发给这个学生的题目编号。"""
    if not student_id:
        return []
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    since = (_dt.now() - _td(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = get_mysql().query(
        "SELECT DISTINCT q_id FROM question_history "
        "WHERE student_id = %s AND created_at >= %s ORDER BY created_at DESC LIMIT %s",
        (student_id, since, limit),
    )
    return [str(r["q_id"]) for r in rows]


__all__ = [
    "list_knowledge_points",
    "resolve_knowledge_point",
    "search_question_bank",
    "select_questions",
    "create_homework",
    "build_exam_doc",
    "build_exam_from_ids",
    "get_questions_by_ids",
    "record_issued_questions",
    "recently_issued_q_ids",
]
