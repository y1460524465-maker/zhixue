"""用户体系：账号、角色、令牌。

设计原则（对应"用户隔离与记忆"的约定）：

* **账号身份**（``user_id``）和**数据主体**（``student_id``）分开。
  学生账号绑定了自己的 ``student_id``；老师账号不绑定，
  对话里指向谁由请求内容决定。
* 令牌用标准库自己签，不引入额外依赖；密钥落在 ``data/.secret_key``，
  9 个进程共用同一份，重启不失效。
* **令牌只在入口解析一次**，之后以 ``user_id`` 的形式随任务包一路传下去。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from zhixue.config import get_settings
from zhixue.logging_setup import get_logger
from zhixue.store import MySQL, get_mysql

logger = get_logger("auth")

TOKEN_TTL = 7 * 24 * 3600  # 7 天
DEFAULT_PASSWORD = "123456"

ROLE_STUDENT = "student"
ROLE_TEACHER = "teacher"


# --------------------------------------------------------------------------- #
# 密钥
# --------------------------------------------------------------------------- #
def get_secret() -> bytes:
    """进程间共享的签名密钥。

    优先环境变量；否则落在 ``data/.secret_key``（已被 .gitignore 排除）。
    """
    env = os.getenv("ZHIXUE_SECRET")
    if env:
        return env.encode("utf-8")

    settings = get_settings()
    key_file: Path = settings.data_dir / ".secret_key"
    if key_file.exists():
        raw = key_file.read_text(encoding="utf-8").strip()
        if raw:
            return raw.encode("utf-8")

    raw = secrets.token_hex(32)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(raw, encoding="utf-8")
    try:  # 尽量收紧权限（Windows 上可能不支持，忽略即可）
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    logger.info("已生成新的签名密钥: %s", key_file)
    return raw.encode("utf-8")


# --------------------------------------------------------------------------- #
# 口令
# --------------------------------------------------------------------------- #
def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()
    return salt, digest


def verify_password(password: str, salt: str, expected: str) -> bool:
    _, digest = hash_password(password, salt)
    return hmac.compare_digest(digest, expected)


# --------------------------------------------------------------------------- #
# 令牌
# --------------------------------------------------------------------------- #
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def create_token(user: dict[str, Any], ttl: int = TOKEN_TTL) -> str:
    payload = {
        "uid": user["user_id"],
        "role": user["role"],
        "sid": user.get("student_id") or "",
        "name": user["display_name"],
        "exp": int(time.time()) + ttl,
    }
    body = _b64e(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    signature = hmac.new(get_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{signature}"


def decode_token(token: str) -> dict[str, Any] | None:
    """验签并解析令牌；任何异常都返回 None（宁可拒绝，不给默认值）。"""
    if not token or "." not in token:
        return None
    body, _, signature = token.partition(".")
    expected = hmac.new(get_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_b64d(body))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    if not payload.get("uid"):
        return None
    return payload


# --------------------------------------------------------------------------- #
# 账号读写
# --------------------------------------------------------------------------- #
def get_user(mysql: MySQL, user_id: str) -> dict[str, Any] | None:
    row = mysql.query_one(
        "SELECT user_id, username, display_name, role, student_id FROM app_user WHERE user_id = %s",
        (user_id,),
    )
    return dict(row) if row else None


def authenticate(mysql: MySQL, username: str, password: str) -> dict[str, Any] | None:
    row = mysql.query_one(
        "SELECT user_id, username, display_name, role, student_id, password_salt, password_hash "
        "FROM app_user WHERE username = %s",
        (username,),
    )
    if not row:
        return None
    if not verify_password(password, row["password_salt"], row["password_hash"]):
        return None
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "student_id": row["student_id"],
    }


def create_user(
    mysql: MySQL,
    *,
    user_id: str,
    username: str,
    display_name: str,
    role: str,
    student_id: str | None = None,
    password: str = DEFAULT_PASSWORD,
) -> None:
    salt, digest = hash_password(password)
    mysql.execute(
        "INSERT INTO app_user "
        "(user_id, username, display_name, role, student_id, password_salt, password_hash, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            user_id, username, display_name, role, student_id, salt, digest,
            time.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )


def ensure_default_users(mysql: MySQL | None = None, password: str = DEFAULT_PASSWORD) -> dict[str, Any]:
    """建默认账号：每个学生一个，外加一个老师账号。

    学生账号名 = 学号小写（如 ``s00001``），老师账号名 = ``teacher``。
    默认口令都是 ``123456``，仅用于本地演示。
    """
    mysql = mysql or get_mysql()
    created_students = 0
    created_teachers = 0

    students = mysql.query("SELECT student_id, name FROM student ORDER BY student_id")
    for row in students:
        username = str(row["student_id"]).lower()
        exists = mysql.query_one("SELECT 1 AS x FROM app_user WHERE username = %s", (username,))
        if exists:
            continue
        create_user(
            mysql,
            user_id=f"U{row['student_id']}",
            username=username,
            display_name=row["name"],
            role=ROLE_STUDENT,
            student_id=row["student_id"],
            password=password,
        )
        created_students += 1

    if not mysql.query_one("SELECT 1 AS x FROM app_user WHERE username = %s", ("teacher",)):
        create_user(
            mysql,
            user_id="UTEACHER",
            username="teacher",
            display_name="演示老师",
            role=ROLE_TEACHER,
            student_id=None,
            password=password,
        )
        created_teachers += 1

    result = {
        "students_created": created_students,
        "teachers_created": created_teachers,
        "default_password": password,
    }
    logger.info("默认账号就绪: %s", result)
    return result


__all__ = [
    "DEFAULT_PASSWORD",
    "ROLE_STUDENT",
    "ROLE_TEACHER",
    "TOKEN_TTL",
    "authenticate",
    "create_token",
    "create_user",
    "decode_token",
    "ensure_default_users",
    "get_secret",
    "get_user",
    "hash_password",
    "verify_password",
]
