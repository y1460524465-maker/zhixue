"""智学统一配置。

设计原则：

* 所有路径都相对项目根目录解析，不再出现硬编码的绝对路径；
* 优先级：环境变量 > ``config.ini`` > 内置默认值；
* 端口/服务地址集中在这里，方便一键改端口。
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path

# zhixue/config.py -> zhixue/ -> 项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = PROJECT_ROOT / "config.ini"


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _load_ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    if path.exists():
        # 原项目在 Windows 下读 config.ini 会撞 GBK 编码错误，这里统一用 utf-8
        parser.read(path, encoding="utf-8")
    return parser


_ini = _load_ini(CONFIG_FILE)


def _ini_get(section: str, option: str, default: str) -> str:
    try:
        value = _ini.get(section, option)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return default
    return value.strip() if isinstance(value, str) else default


def _ini_zhixue(option: str, fallback: str) -> str:
    """先看 ``[zhixue]`` 段，没有就回落到原项目的配置项。

    这样 智学 可以独立配置，又不必改动原有的 ``[mysql]`` / ``[llm]`` 段。
    """
    value = _ini_get("zhixue", option, "")
    return value or fallback


@dataclass
class ServicePorts:
    """架构图上的 9 个进程端口。"""

    main: int = _env_int("ZHIXUE_PORT_MAIN", 8000)
    docgen_agent: int = _env_int("ZHIXUE_PORT_DOCGEN_AGENT", 5010)
    question_agent: int = _env_int("ZHIXUE_PORT_QUESTION_AGENT", 5011)
    grading_agent: int = _env_int("ZHIXUE_PORT_GRADING_AGENT", 5012)
    analysis_agent: int = _env_int("ZHIXUE_PORT_ANALYSIS_AGENT", 5013)
    docgen_mcp: int = _env_int("ZHIXUE_PORT_DOCGEN_MCP", 8010)
    question_mcp: int = _env_int("ZHIXUE_PORT_QUESTION_MCP", 8011)
    grading_mcp: int = _env_int("ZHIXUE_PORT_GRADING_MCP", 8012)
    analysis_mcp: int = _env_int("ZHIXUE_PORT_ANALYSIS_MCP", 8013)

    mcp_path: str = _env("ZHIXUE_MCP_PATH", "/mcp")

    def port(self, name: str) -> int:
        """按别名取端口，``grading`` / ``grading_agent`` 都认。"""
        key = name[: -len("_agent")] if name.endswith("_agent") else name
        table = {
            "main": self.main,
            "docgen": self.docgen_agent,
            "question": self.question_agent,
            "grading": self.grading_agent,
            "analysis": self.analysis_agent,
            "docgen_mcp": self.docgen_mcp,
            "question_mcp": self.question_mcp,
            "grading_mcp": self.grading_mcp,
            "analysis_mcp": self.analysis_mcp,
        }
        if key not in table:
            raise KeyError(f"未知服务名: {name}")
        return table[key]


@dataclass
class Settings:
    """全局配置对象，``from_env()`` 是唯一入口。"""

    app_name: str = "智学"
    host: str = _env("ZHIXUE_HOST", "127.0.0.1")
    ports: ServicePorts = field(default_factory=ServicePorts)

    # ---------- MySQL ----------
    mysql_host: str = _env("ZHIXUE_MYSQL_HOST", _ini_zhixue("mysql_host", _ini_get("mysql", "host", "localhost")))
    mysql_port: int = _env_int("ZHIXUE_MYSQL_PORT", 3306)
    mysql_user: str = _env("ZHIXUE_MYSQL_USER", _ini_zhixue("mysql_user", _ini_get("mysql", "user", "root")))
    mysql_password: str = _env(
        "ZHIXUE_MYSQL_PASSWORD",
        _ini_zhixue("mysql_password", _ini_get("mysql", "password", "12345678")),
    )
    mysql_database: str = _env("ZHIXUE_MYSQL_DATABASE", _ini_zhixue("mysql_database", "zhixue"))

    # ---------- Redis ----------
    redis_host: str = _env("ZHIXUE_REDIS_HOST", _ini_zhixue("redis_host", _ini_get("redis", "host", "localhost")))
    redis_port: int = _env_int("ZHIXUE_REDIS_PORT", 6379)
    redis_password: str = _env("ZHIXUE_REDIS_PASSWORD", _ini_zhixue("redis_password", _ini_get("redis", "password", "")))
    redis_db: int = _env_int("ZHIXUE_REDIS_DB", 0)

    # ---------- Milvus ----------
    milvus_host: str = _env("ZHIXUE_MILVUS_HOST", _ini_zhixue("milvus_host", _ini_get("milvus", "host", "localhost")))
    milvus_port: int = _env_int("ZHIXUE_MILVUS_PORT", 19530)
    milvus_database: str = _env("ZHIXUE_MILVUS_DATABASE", "zhixue")
    milvus_timeout: float = float(_env("ZHIXUE_MILVUS_TIMEOUT", "3"))
    textbook_collection: str = _env("ZHIXUE_MILVUS_TEXTBOOK", "zhixue_textbook")
    question_collection: str = _env("ZHIXUE_MILVUS_QUESTION", "zhixue_question")
    embedding_model_path: str = _env(
        "ZHIXUE_EMBEDDING_MODEL", str(PROJECT_ROOT / "rag_qa" / "models" / "bge-m3")
    )

    # ---------- LLM ----------
    llm_model: str = _env("ZHIXUE_LLM_MODEL", _ini_zhixue("llm_model", _ini_get("llm", "model", "qwen3-max")))
    llm_api_key: str = _env(
        "DASHSCOPE_API_KEY",
        _env("API_KEY", _ini_zhixue("llm_api_key", _ini_get("llm", "dashscope_api_key", ""))),
    )
    llm_base_url: str = _env(
        "ZHIXUE_LLM_BASE_URL",
        _ini_zhixue(
            "llm_base_url",
            _ini_get("llm", "dashscope_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ),
    )
    llm_timeout: int = _env_int("ZHIXUE_LLM_TIMEOUT", 60)

    # ---------- 业务开关 ----------
    # mcp / local：Agent 调工具的方式。local 用于没装 MCP SDK 时的降级。
    tool_transport: str = _env("ZHIXUE_TOOL_TRANSPORT", "mcp")
    # a2a / local：主应用派发任务给 Agent 的方式。
    network_transport: str = _env("ZHIXUE_NETWORK_TRANSPORT", "a2a")

    # ---------- 路径 ----------
    project_root: Path = PROJECT_ROOT
    log_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "logs")
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "zhixue" / "data")
    template_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "zhixue" / "data" / "templates")
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "zhixue" / "data" / "outputs")
    upload_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "zhixue" / "data" / "uploads")
    static_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "zhixue" / "app" / "static")

    # ---------- 检索参数 ----------
    retrieval_k: int = _env_int("ZHIXUE_RETRIEVAL_K", 5)
    candidate_m: int = _env_int("ZHIXUE_CANDIDATE_M", 3)

    def ensure_dirs(self) -> None:
        """创建运行期需要的目录。"""
        for path in (
            self.log_dir,
            self.data_dir,
            self.template_dir,
            self.output_dir,
            self.upload_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    # ---------- 服务地址 ----------
    def url(self, name: str) -> str:
        """按名字取服务地址，例如 ``url("grading_agent")``。"""
        port = self.ports.port(name)
        return f"http://{self.host}:{port}"

    def mcp_url(self, name: str) -> str:
        return f"{self.url(name)}{self.ports.mcp_path}"

_settings: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    """进程内单例配置。"""
    global _settings
    if _settings is None or reload:
        _settings = Settings()
        _settings.ensure_dirs()
    return _settings


__all__ = ["Settings", "ServicePorts", "PROJECT_ROOT", "CONFIG_FILE", "get_settings"]
