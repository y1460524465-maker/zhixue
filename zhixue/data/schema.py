"""智学业务库的建表 DDL。

统一放在一个 ``zhixue`` 库里，不动原项目的 ``subjects_kg``。
表与架构图右下角"工具与数据层"的六个库一一对应：

* 课本向量库   -> ``textbook_chunk``   (+ Milvus 向量索引)
* Word 模板库  -> ``word_template``    (+ data/templates/*.docx)
* 题目向量库   -> ``question_bank``    (+ Milvus 向量索引)
* 学生成绩库   -> ``score_record``
* 错题记录库   -> ``mistake_record``
* 作业答案库   -> ``homework_answer`` / ``submission`` / ``grading_result``

注意：DDL 刻意避开 ``DATETIME DEFAULT CURRENT_TIMESTAMP``（需要 MySQL 5.6.5+）
和 ``JSON`` 列类型（需要 5.7+），在 MySQL 5.5 上会直接报错。
所有时间戳一律由应用层显式写入。
"""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS student (
  student_id   VARCHAR(32)  NOT NULL PRIMARY KEY,
  name         VARCHAR(64)  NOT NULL,
  class_name   VARCHAR(64)  NOT NULL,
  grade        VARCHAR(32)  NOT NULL,
  created_at   DATETIME     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS knowledge_point (
  kp_id        VARCHAR(32)  NOT NULL PRIMARY KEY,
  subject      VARCHAR(32)  NOT NULL,
  name         VARCHAR(128) NOT NULL,
  parent_id    VARCHAR(32)  NULL,
  difficulty   TINYINT      NOT NULL DEFAULT 2,
  description  TEXT         NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS question_bank (
  q_id         VARCHAR(32)  NOT NULL PRIMARY KEY,
  subject      VARCHAR(32)  NOT NULL,
  kp_id        VARCHAR(32)  NOT NULL,
  q_type       VARCHAR(16)  NOT NULL,
  difficulty   TINYINT      NOT NULL DEFAULT 2,
  stem         TEXT         NOT NULL,
  options      TEXT         NULL,
  answer       TEXT         NOT NULL,
  analysis     TEXT         NULL,
  source       VARCHAR(64)  NULL,
  INDEX idx_kp (kp_id),
  INDEX idx_subject (subject)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS homework (
  homework_id  VARCHAR(32)  NOT NULL PRIMARY KEY,
  title        VARCHAR(200) NOT NULL,
  subject      VARCHAR(32)  NOT NULL,
  kp_id        VARCHAR(32)  NULL,
  full_score   INT          NOT NULL DEFAULT 100,
  publish_time DATETIME     NOT NULL,
  due_date     DATE         NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS homework_question (
  homework_id  VARCHAR(32) NOT NULL,
  q_id         VARCHAR(32) NOT NULL,
  seq          INT         NOT NULL,
  score        INT         NOT NULL DEFAULT 10,
  PRIMARY KEY (homework_id, q_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS homework_answer (
  homework_id  VARCHAR(32) NOT NULL,
  q_id         VARCHAR(32) NOT NULL,
  std_answer   TEXT        NOT NULL,
  rubric       TEXT        NULL,
  PRIMARY KEY (homework_id, q_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS submission (
  submission_id VARCHAR(32) NOT NULL PRIMARY KEY,
  homework_id   VARCHAR(32) NOT NULL,
  student_id    VARCHAR(32) NOT NULL,
  submit_time   DATETIME    NOT NULL,
  file_path     VARCHAR(255) NULL,
  status        VARCHAR(16) NOT NULL DEFAULT 'submitted',
  INDEX idx_stu_hw (student_id, homework_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS grading_result (
  grade_id       VARCHAR(32) NOT NULL PRIMARY KEY,
  submission_id  VARCHAR(32) NOT NULL,
  student_id     VARCHAR(32) NOT NULL,
  homework_id    VARCHAR(32) NOT NULL,
  q_id           VARCHAR(32) NOT NULL,
  student_answer TEXT        NULL,
  std_answer     TEXT        NULL,
  is_correct     TINYINT     NOT NULL DEFAULT 0,
  score          FLOAT       NOT NULL DEFAULT 0,
  full_score     FLOAT       NOT NULL DEFAULT 10,
  comment        TEXT        NULL,
  created_at     DATETIME    NOT NULL,
  INDEX idx_stu (student_id),
  INDEX idx_hw (homework_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS score_record (
  score_id     VARCHAR(32) NOT NULL PRIMARY KEY,
  student_id   VARCHAR(32) NOT NULL,
  homework_id  VARCHAR(32) NOT NULL,
  subject      VARCHAR(32) NOT NULL,
  score        FLOAT       NOT NULL,
  full_score   FLOAT       NOT NULL,
  submit_time  DATETIME    NOT NULL,
  kp_scores    TEXT        NULL,
  INDEX idx_stu (student_id),
  INDEX idx_subject (subject)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mistake_record (
  mistake_id      VARCHAR(32) NOT NULL PRIMARY KEY,
  student_id      VARCHAR(32) NOT NULL,
  q_id            VARCHAR(32) NOT NULL,
  kp_id           VARCHAR(32) NOT NULL,
  subject         VARCHAR(32) NOT NULL,
  wrong_count     INT         NOT NULL DEFAULT 1,
  last_wrong_time DATETIME    NOT NULL,
  mastery         FLOAT       NOT NULL DEFAULT 0,
  UNIQUE KEY uk_stu_q (student_id, q_id),
  INDEX idx_kp (kp_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS textbook_chunk (
  chunk_id   VARCHAR(32) NOT NULL PRIMARY KEY,
  subject    VARCHAR(32) NOT NULL,
  kp_id      VARCHAR(32) NULL,
  chapter    VARCHAR(128) NULL,
  title      VARCHAR(200) NOT NULL,
  content    TEXT        NOT NULL,
  source     VARCHAR(128) NULL,
  INDEX idx_kp (kp_id),
  INDEX idx_subject (subject)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS word_template (
  template_id VARCHAR(32) NOT NULL PRIMARY KEY,
  name        VARCHAR(128) NOT NULL,
  doc_type    VARCHAR(32) NOT NULL,
  path        VARCHAR(255) NOT NULL,
  description VARCHAR(255) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS conversation (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  session_id VARCHAR(64) NOT NULL,
  student_id VARCHAR(32) NULL,
  question   TEXT        NOT NULL,
  answer     TEXT        NOT NULL,
  intent     VARCHAR(32) NULL,
  created_at DATETIME    NOT NULL,
  INDEX idx_session (session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def create_schema(mysql) -> None:
    """在目标库上建表（幂等）。"""
    mysql.ensure_database()
    mysql.execute_script(DDL)


__all__ = ["DDL", "create_schema"]
