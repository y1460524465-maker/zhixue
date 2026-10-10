"""学情分析 Agent 的工具集（对应架构图 MCP Analysis :8013/mcp）。

* ``text_to_sql``  -> 自然语言转 SQL（Text-to-SQL）
* ``run_sql``      -> 只读执行 SQL（学生成绩库 / 错题记录库）
* ``student_profile`` / ``weak_knowledge_points`` / ``score_trend`` / ``class_comparison``
* ``write_mistake_records`` -> 接收批改 Agent 的结果，写入错题记录库
"""

from __future__ import annotations

import json
import re
from typing import Any

from zhixue.logging_setup import get_logger
from zhixue.store import get_mysql

logger = get_logger("tools.analysis")

#: 给 Text-to-SQL 用的库表说明
SCHEMA_PROMPT = """
可用表（MySQL 5.5，禁止使用窗口函数、CTE、JSON 函数）：

student(student_id, name, class_name, grade)
knowledge_point(kp_id, subject, name, difficulty, description)
question_bank(q_id, subject, kp_id, q_type, difficulty, stem, answer, analysis)
homework(homework_id, title, subject, kp_id, full_score, publish_time, due_date)
submission(submission_id, homework_id, student_id, submit_time, status)
grading_result(grade_id, submission_id, student_id, homework_id, q_id,
               student_answer, std_answer, is_correct, score, full_score, comment, created_at)
score_record(score_id, student_id, homework_id, subject, score, full_score, submit_time, kp_scores)
mistake_record(mistake_id, student_id, q_id, kp_id, subject, wrong_count, last_wrong_time, mastery)
textbook_chunk(chunk_id, subject, kp_id, chapter, title, content, source)
""".strip()

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|truncate|alter|create|grant|replace|rename|into\s+outfile)\b",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- #
# Text-to-SQL
# --------------------------------------------------------------------------- #
def text_to_sql(question: str, execute: bool = False) -> dict[str, Any]:
    """把自然语言问题转成 SQL，可选直接执行。"""
    from zhixue.llm import LLMClient, LLMError

    prompt = (
        "你是 MySQL 专家。请把下面的问题翻译成一条只读 SELECT 语句。\n"
        f"{SCHEMA_PROMPT}\n\n"
        f"问题：{question}\n\n"
        "要求：只输出 JSON，格式 {\"sql\": \"...\", \"explain\": \"一句话说明\"}。"
        "SQL 必须只读，且尽量加上 LIMIT 50。"
    )
    try:
        payload = LLMClient().chat_json(prompt, fallback={})
    except LLMError as exc:
        logger.warning("Text-to-SQL 失败: %s", exc)
        return {"sql": "", "explain": "", "ok": False, "error": str(exc)}

    sql = str(payload.get("sql", "")).strip().rstrip(";")
    result: dict[str, Any] = {
        "sql": sql,
        "explain": payload.get("explain", ""),
        "ok": False,
    }
    if not sql:
        result["error"] = "模型没有返回 SQL"
        return result
    if _FORBIDDEN.search(sql):
        result["error"] = "生成的 SQL 含写操作，已拒绝执行"
        logger.warning("拒绝执行 SQL: %s", sql)
        return result
    if not re.match(r"^\s*(select|with)\b", sql, re.IGNORECASE):
        result["error"] = "只允许 SELECT 查询"
        return result

    result["ok"] = True
    if execute:
        result["rows"] = run_sql(sql)["rows"]
    return result


def run_sql(sql: str, limit: int = 200) -> dict[str, Any]:
    """只读执行 SQL。任何写操作都会被拒绝。"""
    statement = (sql or "").strip().rstrip(";")
    if not statement:
        raise ValueError("SQL 不能为空")
    if _FORBIDDEN.search(statement):
        raise ValueError("只允许只读查询，检测到写操作")
    if not re.match(r"^\s*(select|with|show|describe|desc)\b", statement, re.IGNORECASE):
        raise ValueError("只允许 SELECT / SHOW / DESC 这类只读语句")
    if re.match(r"^\s*select\b", statement, re.IGNORECASE) and "limit" not in statement.lower():
        statement = f"{statement} LIMIT {limit}"
    rows = [dict(r) for r in get_mysql().query(statement)]
    return {"sql": statement, "rows": rows, "count": len(rows)}


# --------------------------------------------------------------------------- #
# 固定分析视图
# --------------------------------------------------------------------------- #
def student_profile(student_id: str, top_n: int = 5) -> dict[str, Any]:
    """学生画像：基础信息 + 成绩概览 + 薄弱知识点 + 高频错题。"""
    mysql = get_mysql()
    student = mysql.query_one("SELECT * FROM student WHERE student_id = %s", (student_id,))
    if not student:
        raise ValueError(f"学生不存在: {student_id}")

    overview = mysql.query_one(
        "SELECT COUNT(*) AS homework_count, AVG(score) AS avg_score, AVG(score / full_score) AS avg_rate, "
        "       MAX(score / full_score) AS best_rate, MIN(score / full_score) AS worst_rate "
        "FROM score_record WHERE student_id = %s",
        (student_id,),
    ) or {}

    kp_rows = mysql.query(
        "SELECT sr.homework_id, sr.kp_scores FROM score_record sr WHERE sr.student_id = %s",
        (student_id,),
    )
    bucket: dict[str, list[float]] = {}
    for row in kp_rows:
        try:
            scores = json.loads(row["kp_scores"] or "{}")
        except ValueError:
            scores = {}
        for kp_id, rate in scores.items():
            bucket.setdefault(kp_id, []).append(float(rate))

    names = {
        r["kp_id"]: r
        for r in mysql.query("SELECT kp_id, name, subject, difficulty FROM knowledge_point")
    }
    mastery = [
        {
            "kp_id": kp_id,
            "name": names.get(kp_id, {}).get("name", kp_id),
            "subject": names.get(kp_id, {}).get("subject", ""),
            "rate": round(sum(vals) / len(vals), 3),
            "samples": len(vals),
        }
        for kp_id, vals in bucket.items()
        if vals
    ]
    mastery.sort(key=lambda x: x["rate"])

    top_mistakes = [
        dict(r)
        for r in mysql.query(
            "SELECT m.q_id, m.kp_id, m.subject, m.wrong_count, m.mastery, q.stem "
            "FROM mistake_record m JOIN question_bank q ON q.q_id = m.q_id "
            "WHERE m.student_id = %s ORDER BY m.wrong_count DESC, m.mastery ASC LIMIT %s",
            (student_id, top_n),
        )
    ]

    return {
        "student": {
            "student_id": student["student_id"],
            "name": student["name"],
            "class_name": student["class_name"],
            "grade": student["grade"],
        },
        "overview": {
            "homework_count": int(overview.get("homework_count") or 0),
            "avg_score": round(float(overview.get("avg_score") or 0), 1),
            "avg_rate": round(float(overview.get("avg_rate") or 0), 3),
            "best_rate": round(float(overview.get("best_rate") or 0), 3),
            "worst_rate": round(float(overview.get("worst_rate") or 0), 3),
        },
        "mastery": mastery,
        "weak_points": mastery[:top_n],
        "strong_points": list(reversed(mastery[-top_n:])) if len(mastery) > 1 else mastery,
        "top_mistakes": top_mistakes,
    }


def weak_knowledge_points(student_id: str, top_n: int = 3) -> list[dict[str, Any]]:
    return student_profile(student_id, top_n=top_n)["weak_points"]


def score_trend(student_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """成绩趋势（按提交时间正序）。"""
    rows = get_mysql().query(
        "SELECT s.homework_id, h.title, s.subject, s.score, s.full_score, s.submit_time "
        "FROM score_record s LEFT JOIN homework h ON h.homework_id = s.homework_id "
        "WHERE s.student_id = %s ORDER BY s.submit_time DESC LIMIT %s",
        (student_id, limit),
    )
    result = [dict(r) for r in rows]
    for item in result:
        item["rate"] = round(float(item["score"]) / float(item["full_score"] or 1), 3)
    result.reverse()
    return result


def class_comparison(student_id: str) -> dict[str, Any]:
    """个人 vs 班级平均。"""
    mysql = get_mysql()
    student = mysql.query_one("SELECT class_name FROM student WHERE student_id = %s", (student_id,))
    if not student:
        raise ValueError(f"学生不存在: {student_id}")
    class_name = student["class_name"]

    mine = mysql.query_one(
        "SELECT AVG(s.score / s.full_score) AS rate FROM score_record s WHERE s.student_id = %s",
        (student_id,),
    ) or {}
    klass = mysql.query_one(
        "SELECT AVG(s.score / s.full_score) AS rate FROM score_record s "
        "JOIN student st ON st.student_id = s.student_id WHERE st.class_name = %s",
        (class_name,),
    ) or {}
    my_rate = float(mine.get("rate") or 0)
    class_rate = float(klass.get("rate") or 0)
    return {
        "class_name": class_name,
        "my_rate": round(my_rate, 3),
        "class_rate": round(class_rate, 3),
        "gap": round(my_rate - class_rate, 3),
        "position": "高于班级平均" if my_rate >= class_rate else "低于班级平均",
    }


def frequent_mistakes(subject: str | None = None, top_n: int = 10) -> list[dict[str, Any]]:
    """全校/全学科高频错题，给教研用。"""
    sql = (
        "SELECT m.q_id, m.kp_id, m.subject, q.stem, COUNT(*) AS wrong_students, "
        "       SUM(m.wrong_count) AS wrong_times "
        "FROM mistake_record m JOIN question_bank q ON q.q_id = m.q_id "
    )
    params: list[Any] = []
    if subject:
        sql += "WHERE m.subject = %s "
        params.append(subject)
    sql += "GROUP BY m.q_id, m.kp_id, m.subject, q.stem ORDER BY wrong_students DESC LIMIT %s"
    params.append(top_n)
    return [dict(r) for r in get_mysql().query(sql, tuple(params))]


def write_mistake_records(student_id: str, homework_id: str | None = None) -> dict[str, Any]:
    """接收批改结果并写入错题记录库（供批改 Agent 通过 A2A 调用）。"""
    from zhixue.tools.grading_tools import sync_mistake_records

    return sync_mistake_records(student_id, homework_id)


__all__ = [
    "SCHEMA_PROMPT",
    "text_to_sql",
    "run_sql",
    "student_profile",
    "weak_knowledge_points",
    "score_trend",
    "class_comparison",
    "frequent_mistakes",
    "write_mistake_records",
]
