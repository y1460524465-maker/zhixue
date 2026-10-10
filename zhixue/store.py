"""数据层：MySQL（业务数据） + Redis（会话/缓存）。

连接都是懒加载的，并且允许降级：

* MySQL 连不上 -> 抛出 ``StoreUnavailable``，调用方自己决定怎么兜；
* Redis 连不上 -> 自动退化成进程内字典，功能不断（单机 demo 够用）。
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Sequence

from zhixue.config import Settings, get_settings
from zhixue.logging_setup import get_logger

logger = get_logger("store")


class StoreUnavailable(RuntimeError):
    """底层存储不可用。"""


# --------------------------------------------------------------------------- #
# MySQL
# --------------------------------------------------------------------------- #
class MySQL:
    """带自动重连的 MySQL 封装。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._conn: Any = None
        self._lock = threading.RLock()

    # -- 连接管理 ---------------------------------------------------------- #
    def _connect(self, database: str | None = None) -> Any:
        import pymysql

        return pymysql.connect(
            host=self.settings.mysql_host,
            port=self.settings.mysql_port,
            user=self.settings.mysql_user,
            password=self.settings.mysql_password,
            database=database,
            charset="utf8mb4",
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def ensure_database(self) -> None:
        """建库（表由 ``zhixue.data.schema`` 负责）。"""
        try:
            conn = self._connect()
        except Exception as exc:  # pragma: no cover - 依赖外部服务
            raise StoreUnavailable(f"MySQL 连接失败: {exc}") from exc
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self.settings.mysql_database}` "
                    "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
                )
        finally:
            conn.close()

    @property
    def connection(self) -> Any:
        with self._lock:
            if self._conn is None:
                try:
                    self._conn = self._connect(self.settings.mysql_database)
                except Exception as exc:
                    raise StoreUnavailable(f"MySQL 连接失败: {exc}") from exc
            else:
                try:
                    self._conn.ping(reconnect=True)
                except Exception:
                    try:
                        self._conn = self._connect(self.settings.mysql_database)
                    except Exception as exc:
                        raise StoreUnavailable(f"MySQL 重连失败: {exc}") from exc
            return self._conn

    # -- 查询 -------------------------------------------------------------- #
    def query(self, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            conn = self.connection
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                return list(cur.fetchall())

    def query_one(self, sql: str, params: Sequence[Any] | None = None) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> int:
        """执行写语句，返回受影响行数。"""
        with self._lock:
            conn = self.connection
            with conn.cursor() as cur:
                rows = cur.execute(sql, params or ())
                return int(rows or 0)

    def execute_many(self, sql: str, rows: Iterable[Sequence[Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        with self._lock:
            conn = self.connection
            with conn.cursor() as cur:
                affected = cur.executemany(sql, rows)
                return int(affected or 0)

    def execute_script(self, script: str) -> None:
        """执行多语句 SQL 脚本（建表用）。"""
        statements = [s.strip() for s in script.split(";") if s.strip()]
        with self._lock:
            conn = self.connection
            with conn.cursor() as cur:
                for stmt in statements:
                    if stmt.startswith("--"):
                        continue
                    cur.execute(stmt)

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        with self._lock:
            conn = self.connection
            conn.begin()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def ping(self) -> bool:
        try:
            self.connection.ping(reconnect=True)
            return True
        except Exception:
            return False

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None


# --------------------------------------------------------------------------- #
# 缓存：Redis，连不上就退化成本地字典
# --------------------------------------------------------------------------- #
class _MemoryCache:
    """极简内存缓存，接口对齐 Redis 用到的那几个方法。"""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}
        self._lock = threading.RLock()

    def _alive(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expire_at = item
        if expire_at is not None and expire_at < time.time():
            self._data.pop(key, None)
            return None
        return value

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._alive(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        with self._lock:
            self._data[key] = (value, time.time() + ex if ex else None)

    def delete(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._data.pop(key, None)

    def keys(self, pattern: str = "*") -> list[str]:
        prefix = pattern.rstrip("*")
        with self._lock:
            return [k for k in list(self._data) if k.startswith(prefix) and self._alive(k) is not None]

    def ping(self) -> bool:
        return True


class Cache:
    """会话草稿 / 结果缓存。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: Any = None
        self._memory = _MemoryCache()
        self.degraded = False

    @property
    def client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import redis

            client = redis.Redis(
                host=self.settings.redis_host,
                port=self.settings.redis_port,
                password=self.settings.redis_password or None,
                db=self.settings.redis_db,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            client.ping()
            self._client = client
            logger.info("Redis 连接成功 %s:%s", self.settings.redis_host, self.settings.redis_port)
        except Exception as exc:
            if not self.degraded:
                logger.warning("Redis 不可用(%s)，已降级为进程内缓存", exc)
            self.degraded = True
            self._client = self._memory
        return self._client

    # -- JSON 读写 --------------------------------------------------------- #
    def get_json(self, key: str) -> Any | None:
        try:
            raw = self.client.get(key)
        except Exception:
            self.degraded = True
            self._client = self._memory
            raw = self._memory.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    def set_json(self, key: str, value: Any, ttl: int = 3600) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        try:
            self.client.set(key, payload, ex=ttl)
        except Exception:
            self.degraded = True
            self._client = self._memory
            self._memory.set(key, payload, ex=ttl)

    def delete(self, *keys: str) -> None:
        try:
            self.client.delete(*keys)
        except Exception:
            self._memory.delete(*keys)

    def ping(self) -> bool:
        """只有真正在用 Redis 时才算 True（降级到内存缓存时返回 False）。"""
        self.client  # 触发一次解析（连不上会自动降级）
        if self.degraded:
            return False
        try:
            return bool(self._client.ping())
        except Exception:
            self.degraded = True
            self._client = self._memory
            return False

    @property
    def backend(self) -> str:
        self.client
        return "memory" if self.degraded else "redis"


# --------------------------------------------------------------------------- #
# 进程内单例
# --------------------------------------------------------------------------- #
_mysql: MySQL | None = None
_cache: Cache | None = None


def get_mysql() -> MySQL:
    global _mysql
    if _mysql is None:
        _mysql = MySQL()
    return _mysql


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = Cache()
    return _cache


DRAFT_KEY = "zhixue:draft:{session_id}"


def load_draft(session_id: str) -> dict[str, Any]:
    return get_cache().get_json(DRAFT_KEY.format(session_id=session_id)) or {}


def save_draft(session_id: str, draft: dict[str, Any], ttl: int = 3600) -> None:
    get_cache().set_json(DRAFT_KEY.format(session_id=session_id), draft, ttl=ttl)


def clear_draft(session_id: str) -> None:
    get_cache().delete(DRAFT_KEY.format(session_id=session_id))


__all__ = [
    "MySQL",
    "Cache",
    "StoreUnavailable",
    "get_mysql",
    "get_cache",
    "load_draft",
    "save_draft",
    "clear_draft",
]
