"""日志：控制台 + 文件双写，带 task_id 上下文。"""

from __future__ import annotations

import contextvars
import logging
import sys
from pathlib import Path

from zhixue.config import get_settings

_task_id: contextvars.ContextVar[str] = contextvars.ContextVar("zhixue_task_id", default="-")

_CONFIGURED = False


class _TaskIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.task_id = _task_id.get()
        return True


def set_task_id(task_id: str) -> None:
    """把一个 trace id 绑到当前上下文，之后所有日志都会带上它。"""
    _task_id.set(task_id)


def get_task_id() -> str:
    return _task_id.get()


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """幂等地配置根 logger，返回 zhixue 的 logger。"""
    global _CONFIGURED
    logger = logging.getLogger("zhixue")
    if _CONFIGURED:
        return logger

    settings = get_settings()
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(name)s | task=%(task_id)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    task_filter = _TaskIdFilter()

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    stream.addFilter(task_filter)

    log_file: Path = settings.log_dir / "zhixue.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.addFilter(task_filter)

    logger.handlers.clear()
    logger.addHandler(stream)
    logger.addHandler(file_handler)
    logger.setLevel(level)
    logger.propagate = False
    _CONFIGURED = True
    return logger


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"zhixue.{name}" if name != "zhixue" else "zhixue")


__all__ = ["setup_logging", "get_logger", "set_task_id", "get_task_id"]
