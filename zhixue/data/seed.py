"""生成「智学」的仿真数据。

用法::

    python -m zhixue.data.seed            # 增量写入（表存在就跳过）
    python -m zhixue.data.seed --reset    # 清空后重建

产出：

* MySQL ``zhixue`` 库的 13 张表
* ``data/templates/*.docx`` 四套 Word 模板
* ``data/outputs/answer_sheet_*.png`` 若干张答题卡图片（供 OCR 批改演示）
"""

from __future__ import annotations

import argparse
import json
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from zhixue.config import get_settings
from zhixue.data.content import (
    CLASSES,
    KNOWLEDGE_POINTS,
    STUDENT_NAMES,
    SUBJECTS,
)
from zhixue.data.templates import build_templates
from zhixue.data.schema import create_schema
from zhixue.logging_setup import get_logger, setup_logging
from zhixue.store import StoreUnavailable, get_mysql

logger = get_logger("data.seed")

RANDOM_SEED = 20251010

TABLES = [
    "grading_result",
    "mistake_record",
    "score_record",
    "submission",
    "homework_answer",
    "homework_question",
    "homework",
    "question_bank",
    "knowledge_point",
    "textbook_chunk",
    "word_template",
    "student",
    "conversation",
]

#: 每份作业的题目数量
QUESTIONS_PER_HOMEWORK = 5
QUESTION_SCORE = 20


def _uid(prefix: str, seq: int) -> str:
    return f"{prefix}{seq:05d}"


def _now(offset_days: int = 0) -> str:
    return (datetime.now() - timedelta(days=offset_days)).strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- #
# 建表 / 清空
# --------------------------------------------------------------------------- #
def reset_tables(mysql) -> None:
    for table in TABLES:
        mysql.execute(f"TRUNCATE TABLE `{table}`")
    logger.info("已清空 %d 张表", len(TABLES))


# --------------------------------------------------------------------------- #
# 各表数据
# --------------------------------------------------------------------------- #
def seed_students(mysql, rng: random.Random) -> list[dict[str, Any]]:
    students: list[dict[str, Any]] = []
    for index, name in enumerate(STUDENT_NAMES, start=1):
        class_name, grade = CLASSES[(index - 1) % len(CLASSES)]
        students.append(
            {
                "student_id": _uid("S", index),
                "name": name,
                "class_name": class_name,
                "grade": grade,
                "ability": rng.uniform(0.45, 0.95),
            }
        )
    mysql.execute_many(
        "INSERT INTO student (student_id, name, class_name, grade, created_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        [
            (s["student_id"], s["name"], s["class_name"], s["grade"], _now(120))
            for s in students
        ],
    )
    logger.info("写入学生 %d 名", len(students))
    return students


def seed_knowledge_points(mysql) -> None:
    rows = [
        (kp["kp_id"], kp["subject"], kp["name"], None, kp["difficulty"], kp["description"])
        for kp in KNOWLEDGE_POINTS
    ]
    mysql.execute_many(
        "INSERT INTO knowledge_point (kp_id, subject, name, parent_id, difficulty, description) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        rows,
    )
    logger.info("写入知识点 %d 个", len(rows))


def seed_questions(mysql) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    seq = 0
    for kp in KNOWLEDGE_POINTS:
        for item in kp["questions"]:
            seq += 1
            questions.append(
                {
                    "q_id": _uid("Q", seq),
                    "subject": kp["subject"],
                    "kp_id": kp["kp_id"],
                    "q_type": item["q_type"],
                    "difficulty": item["difficulty"],
                    "stem": item["stem"],
                    "options": json.dumps(item.get("options") or [], ensure_ascii=False),
                    "answer": item["answer"],
                    "analysis": item.get("analysis", ""),
                    "source": f"{kp['subject']}·{kp['name']}",
                }
            )
    mysql.execute_many(
        "INSERT INTO question_bank "
        "(q_id, subject, kp_id, q_type, difficulty, stem, options, answer, analysis, source) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        [
            (
                q["q_id"], q["subject"], q["kp_id"], q["q_type"], q["difficulty"],
                q["stem"], q["options"], q["answer"], q["analysis"], q["source"],
            )
            for q in questions
        ],
    )
    logger.info("写入题目 %d 道", len(questions))
    return questions


def seed_homeworks(
    mysql, questions: list[dict[str, Any]], rng: random.Random
) -> list[dict[str, Any]]:
    """每门学科挑若干知识点，各出一份作业。"""
    by_kp: dict[str, list[dict[str, Any]]] = {}
    for q in questions:
        by_kp.setdefault(q["kp_id"], []).append(q)

    homeworks: list[dict[str, Any]] = []
    seq = 0
    for subject in SUBJECTS:
        kps = [kp for kp in KNOWLEDGE_POINTS if kp["subject"] == subject]
        for kp in kps[:2]:  # 每学科前两个知识点各出一份作业
            seq += 1
            pool = by_kp.get(kp["kp_id"], [])
            picked = pool[:QUESTIONS_PER_HOMEWORK]
            homeworks.append(
                {
                    "homework_id": _uid("HW", seq),
                    "title": f"{subject}·{kp['name']} 专项作业",
                    "subject": subject,
                    "kp_id": kp["kp_id"],
                    "kp_name": kp["name"],
                    "full_score": QUESTION_SCORE * len(picked),
                    "publish_days_ago": 21 - seq * 2,
                    "questions": picked,
                }
            )

    for hw in homeworks:
        published = _now(max(hw["publish_days_ago"], 0))
        due = (datetime.now() + timedelta(days=7 - hw["publish_days_ago"])).strftime("%Y-%m-%d")
        mysql.execute(
            "INSERT INTO homework (homework_id, title, subject, kp_id, full_score, publish_time, due_date) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (hw["homework_id"], hw["title"], hw["subject"], hw["kp_id"], hw["full_score"], published, due),
        )
        mysql.execute_many(
            "INSERT INTO homework_question (homework_id, q_id, seq, score) VALUES (%s, %s, %s, %s)",
            [(hw["homework_id"], q["q_id"], i + 1, QUESTION_SCORE) for i, q in enumerate(hw["questions"])],
        )
        mysql.execute_many(
            "INSERT INTO homework_answer (homework_id, q_id, std_answer, rubric) VALUES (%s, %s, %s, %s)",
            [
                (
                    hw["homework_id"],
                    q["q_id"],
                    q["answer"],
                    "；".join(
                        filter(
                            None,
                            [
                                "答案正确性",
                                "关键术语是否出现" if q["q_type"] == "简答" else "",
                                "推理过程是否完整" if q["q_type"] == "简答" else "",
                            ],
                        )
                    ),
                )
                for q in hw["questions"]
            ],
        )
    logger.info("写入作业 %d 份", len(homeworks))
    return homeworks


def _simulate_answer(question: dict[str, Any], correct: bool, rng: random.Random) -> str:
    """按题目类型编一个像样的学生作答。"""
    if correct:
        return question["answer"]
    options = json.loads(question["options"] or "[]")
    if question["q_type"] in ("单选", "多选") and options:
        letters = [o.strip()[:1] for o in options if o.strip()]
        wrong = [x for x in letters if x != question["answer"]]
        return rng.choice(wrong) if wrong else "未作答"
    if question["q_type"] == "判断":
        return "错" if question["answer"] == "对" else "对"
    # 简答：给一个不完整答案
    text = str(question["answer"])
    cut = max(len(text) // 3, 6)
    return text[:cut] + "……（回答不完整）"


def seed_submissions(
    mysql, students: list[dict[str, Any]], homeworks: list[dict[str, Any]], rng: random.Random
) -> dict[str, int]:
    submissions: list[tuple] = []
    grading_rows: list[tuple] = []
    score_rows: list[tuple] = []
    mistake_acc: dict[tuple[str, str], dict[str, Any]] = {}

    sub_seq = 0
    grade_seq = 0
    score_seq = 0
    kp_difficulty = {kp["kp_id"]: kp["difficulty"] for kp in KNOWLEDGE_POINTS}

    for hw in homeworks:
        for student in students:
            # 约 15% 缺交；但 S00001 保证全交，方便按文档里的示例直接演示
            if student["student_id"] != "S00001" and rng.random() < 0.15:
                continue
            sub_seq += 1
            submission_id = _uid("SUB", sub_seq)
            submit_time = _now(max(hw["publish_days_ago"] - rng.randint(0, 4), 0))
            submissions.append(
                (submission_id, hw["homework_id"], student["student_id"], submit_time, None, "graded")
            )

            total_score = 0.0
            kp_scores: dict[str, dict[str, float]] = {}
            for question in hw["questions"]:
                grade_seq += 1
                difficulty = kp_difficulty.get(question["kp_id"], 2)
                p_correct = student["ability"] - 0.07 * (difficulty - 2)
                correct = rng.random() < max(min(p_correct, 0.97), 0.05)
                student_answer = _simulate_answer(question, correct, rng)

                if correct:
                    score = float(QUESTION_SCORE)
                    comment = "回答正确，思路清晰。"
                else:
                    partial = rng.choice([0.0, 0.4, 0.6])
                    score = round(QUESTION_SCORE * partial, 1)
                    comment = "答案有偏差，请对照解析重新梳理关键概念。"
                    key = (student["student_id"], question["q_id"])
                    record = mistake_acc.setdefault(
                        key,
                        {
                            "student_id": student["student_id"],
                            "q_id": question["q_id"],
                            "kp_id": question["kp_id"],
                            "subject": question["subject"],
                            "wrong_count": 0,
                            "last_wrong_time": submit_time,
                            "scores": [],
                        },
                    )
                    record["wrong_count"] += 1
                    record["last_wrong_time"] = max(record["last_wrong_time"], submit_time)
                    record["scores"].append(score / QUESTION_SCORE)

                total_score += score
                bucket = kp_scores.setdefault(question["kp_id"], {"score": 0.0, "full": 0.0})
                bucket["score"] += score
                bucket["full"] += QUESTION_SCORE

                grading_rows.append(
                    (
                        _uid("G", grade_seq), submission_id, student["student_id"], hw["homework_id"],
                        question["q_id"], student_answer, question["answer"], int(correct),
                        score, float(QUESTION_SCORE), comment, submit_time,
                    )
                )

            score_seq += 1
            score_rows.append(
                (
                    _uid("SC", score_seq), student["student_id"], hw["homework_id"], hw["subject"],
                    round(total_score, 1), float(hw["full_score"]), submit_time,
                    json.dumps(
                        {k: round(v["score"] / v["full"], 3) for k, v in kp_scores.items() if v["full"]},
                        ensure_ascii=False,
                    ),
                )
            )

    mysql.execute_many(
        "INSERT INTO submission (submission_id, homework_id, student_id, submit_time, file_path, status) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        submissions,
    )
    mysql.execute_many(
        "INSERT INTO grading_result "
        "(grade_id, submission_id, student_id, homework_id, q_id, student_answer, std_answer, "
        " is_correct, score, full_score, comment, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        grading_rows,
    )
    mysql.execute_many(
        "INSERT INTO score_record "
        "(score_id, student_id, homework_id, subject, score, full_score, submit_time, kp_scores) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        score_rows,
    )

    mistake_rows = []
    for seq, record in enumerate(mistake_acc.values(), start=1):
        mastery = round(sum(record["scores"]) / len(record["scores"]), 3) if record["scores"] else 0.0
        mistake_rows.append(
            (
                _uid("M", seq), record["student_id"], record["q_id"], record["kp_id"],
                record["subject"], record["wrong_count"], record["last_wrong_time"], mastery,
            )
        )
    mysql.execute_many(
        "INSERT INTO mistake_record "
        "(mistake_id, student_id, q_id, kp_id, subject, wrong_count, last_wrong_time, mastery) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        mistake_rows,
    )

    logger.info(
        "写入提交 %d 份 / 批改明细 %d 条 / 成绩 %d 条 / 错题 %d 条",
        len(submissions), len(grading_rows), len(score_rows), len(mistake_rows),
    )
    return {
        "submissions": len(submissions),
        "grading": len(grading_rows),
        "scores": len(score_rows),
        "mistakes": len(mistake_rows),
    }


def seed_textbook(mysql) -> None:
    rows: list[tuple] = []
    seq = 0
    for kp in KNOWLEDGE_POINTS:
        for index, paragraph in enumerate(kp["textbook"], start=1):
            seq += 1
            rows.append(
                (
                    _uid("TB", seq), kp["subject"], kp["kp_id"], kp["chapter"],
                    f"{kp['name']}（第 {index} 讲）", paragraph,
                    f"智学教研中心 · {kp['subject']}",
                )
            )
    mysql.execute_many(
        "INSERT INTO textbook_chunk (chunk_id, subject, kp_id, chapter, title, content, source) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        rows,
    )
    logger.info("写入课本语料 %d 段", len(rows))


def seed_word_templates(mysql) -> None:
    records = build_templates()
    mysql.execute_many(
        "INSERT INTO word_template (template_id, name, doc_type, path, description) "
        "VALUES (%s, %s, %s, %s, %s)",
        [(r["template_id"], r["name"], r["doc_type"], r["path"], r["description"]) for r in records],
    )
    logger.info("写入 Word 模板 %d 套", len(records))


def _load_cjk_font(size: int):
    from PIL import ImageFont

    candidates = [
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\simsun.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:  # pragma: no cover
                continue
    return ImageFont.load_default()


def seed_answer_sheet_images(
    mysql, students: list[dict[str, Any]], homeworks: list[dict[str, Any]], limit: int = 3
) -> list[str]:
    """把若干份提交渲染成答题卡图片，供 OCR 识别演示。"""
    from PIL import Image, ImageDraw

    settings = get_settings()
    outputs = settings.output_dir
    outputs.mkdir(parents=True, exist_ok=True)

    targets = homeworks[:limit]
    created: list[str] = []
    for hw in targets:
        # 固定用 S00001，保证"批改 S00001 的 HW00001"能直接走 OCR
        student = students[0]
        rows = mysql.query(
            "SELECT g.q_id, g.student_answer, q.stem "
            "FROM grading_result g JOIN question_bank q ON q.q_id = g.q_id "
            "WHERE g.homework_id = %s AND g.student_id = %s ORDER BY q.q_id",
            (hw["homework_id"], student["student_id"]),
        )
        if not rows:
            continue

        width, line_height = 900, 34
        height = 140 + line_height * (len(rows) * 3 + 4)
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        title_font = _load_cjk_font(26)
        font = _load_cjk_font(18)

        draw.text((40, 30), "智学 · 作业答题卡", fill="black", font=title_font)
        draw.text(
            (40, 75),
            f"姓名: {student['name']}   学号: {student['student_id']}   作业编号: {hw['homework_id']}",
            fill="black",
            font=font,
        )
        draw.line((40, 110, width - 40, 110), fill="black", width=2)

        y = 125
        for index, row in enumerate(rows, start=1):
            stem = str(row["stem"]).replace("\n", " ")[:34]
            answer = str(row["student_answer"]).replace("\n", " ")[:40]
            draw.text((40, y), f"{index}. 题目: {stem}", fill="black", font=font)
            draw.text((40, y + line_height), f"   作答: {answer}", fill="black", font=font)
            y += line_height * 3

        path = outputs / f"answer_sheet_{hw['homework_id']}_{student['student_id']}.png"
        image.save(path)
        created.append(str(path))

        mysql.execute(
            "UPDATE submission SET file_path = %s WHERE homework_id = %s AND student_id = %s",
            (str(path), hw["homework_id"], student["student_id"]),
        )
    logger.info("生成答题卡图片 %d 张", len(created))
    return created


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def seed(reset: bool = False, with_images: bool = True) -> dict[str, Any]:
    settings = get_settings()
    settings.ensure_dirs()
    mysql = get_mysql()
    mysql.ensure_database()
    create_schema(mysql)
    if reset:
        reset_tables(mysql)
    elif mysql.query_one("SELECT COUNT(*) AS c FROM student")["c"]:
        logger.info("检测到已有数据，跳过仿真数据生成（需要重建请加 --reset）")
        return {"skipped": True}

    rng = random.Random(RANDOM_SEED)
    students = seed_students(mysql, rng)
    seed_knowledge_points(mysql)
    questions = seed_questions(mysql)
    homeworks = seed_homeworks(mysql, questions, rng)
    stats = seed_submissions(mysql, students, homeworks, rng)
    seed_textbook(mysql)
    seed_word_templates(mysql)
    images = seed_answer_sheet_images(mysql, students, homeworks) if with_images else []

    summary = {
        "students": len(students),
        "knowledge_points": len(KNOWLEDGE_POINTS),
        "questions": len(questions),
        "homeworks": len(homeworks),
        "images": images,
        **stats,
    }
    logger.info("仿真数据生成完成: %s", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="生成智学仿真数据")
    parser.add_argument("--reset", action="store_true", help="清空既有数据后重建")
    parser.add_argument("--no-images", action="store_true", help="不生成答题卡图片")
    args = parser.parse_args()

    setup_logging()
    try:
        summary = seed(reset=args.reset, with_images=not args.no_images)
    except StoreUnavailable as exc:
        raise SystemExit(
            f"无法连接 MySQL: {exc}\n"
            f"请检查 config.ini 的 [mysql] 配置，或先启动数据库。"
        ) from exc
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
