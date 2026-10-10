"""一键启动智学的全部 9 个进程。

    python run_all.py                # 启动 MCP(4) + Agent(4) + 主应用(1)
    python run_all.py --check        # 只做环境自检，不启动
    python run_all.py --only main    # 只起主应用
    python run_all.py --mode local   # 进程内模式（不需要 MCP/A2A SDK）

端口分配（与架构图一致）：

    main :8000
    docgen :5010   question :5011   grading :5012   analysis :5013
    MCP docgen :8010/mcp  question :8011/mcp  grading :8012/mcp  analysis :8013/mcp
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass

from zhixue.config import get_settings
from zhixue.logging_setup import setup_logging


@dataclass
class Proc:
    name: str
    module: str
    port: int
    kind: str  # mcp / agent / main

    def command(self) -> list[str]:
        if self.kind == "main":
            return [sys.executable, "-m", "zhixue.app.main"]
        return [sys.executable, "-m", self.module]


def build_procs() -> list[Proc]:
    ports = get_settings().ports
    return [
        Proc("MCP DocGen", "zhixue.mcp_servers.docgen_mcp", ports.docgen_mcp, "mcp"),
        Proc("MCP Question", "zhixue.mcp_servers.question_mcp", ports.question_mcp, "mcp"),
        Proc("MCP Grading", "zhixue.mcp_servers.grading_mcp", ports.grading_mcp, "mcp"),
        Proc("MCP Analysis", "zhixue.mcp_servers.analysis_mcp", ports.analysis_mcp, "mcp"),
        Proc("DocGenAgent", "zhixue.agents.docgen_agent", ports.docgen_agent, "agent"),
        Proc("QuestionAgent", "zhixue.agents.question_agent", ports.question_agent, "agent"),
        Proc("GradingAgent", "zhixue.agents.grading_agent", ports.grading_agent, "agent"),
        Proc("AnalysisAgent", "zhixue.agents.analysis_agent", ports.analysis_agent, "agent"),
        Proc("Main", "zhixue.app.main", ports.main, "main"),
    ]


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #
def check_environment() -> tuple[bool, list[str]]:
    settings = get_settings()
    notes: list[str] = []
    ok = True

    def note(line: str, good: bool) -> None:
        nonlocal ok
        notes.append(("  [OK]   " if good else "  [MISS] ") + line)
        if not good:
            ok = False

    # 依赖
    for module, hint in [
        ("fastapi", "pip install fastapi uvicorn"),
        ("uvicorn", "pip install fastapi uvicorn"),
        ("pymysql", "pip install pymysql"),
        ("openai", "pip install openai"),
        ("docx", "pip install python-docx"),
        ("fastmcp", "pip install fastmcp   （或用 --mode local 跳过）"),
        ("a2a", "pip install a2a-sdk       （或用 --mode local 跳过）"),
    ]:
        try:
            __import__(module)
            note(f"依赖 {module}", True)
        except ImportError:
            note(f"依赖 {module} 缺失 -> {hint}", False)

    # MySQL
    try:
        from zhixue.store import get_mysql

        get_mysql().ensure_database()
        note(f"MySQL {settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}", True)
    except Exception as exc:  # noqa: BLE001
        note(f"MySQL 不可用：{exc}", False)

    # Redis（可选）
    try:
        from zhixue.store import get_cache

        cache = get_cache()
        if cache.ping():
            note(f"Redis {settings.redis_host}:{settings.redis_port} 已连接", True)
        else:
            note(
                f"Redis {settings.redis_host}:{settings.redis_port} 未连接"
                "（已降级为进程内缓存，会话补槽功能不受影响）",
                True,
            )
    except Exception as exc:  # noqa: BLE001
        note(f"Redis 不可用（会降级为内存缓存）：{exc}", True)

    # Milvus（可选）
    try:
        from zhixue.vector import get_retriever

        backend = get_retriever().backend
        note(
            f"向量检索后端 = {backend}"
            + ("" if backend == "milvus" else "（Milvus 未连接，已降级关键词检索，功能可用）"),
            True,
        )
    except Exception as exc:  # noqa: BLE001
        note(f"向量检索初始化异常：{exc}", True)

    # LLM Key
    note("模型 API Key 已配置" if settings.llm_api_key else "缺少 DASHSCOPE_API_KEY（LLM 功能会降级）", bool(settings.llm_api_key))

    return ok, notes


# --------------------------------------------------------------------------- #
# 启动
# --------------------------------------------------------------------------- #
def wait_for_http(port: int, timeout: float = 25.0) -> bool:
    import httpx

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0)
            return True
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="启动智学全栈")
    parser.add_argument("--check", action="store_true", help="只做环境自检")
    parser.add_argument(
        "--only", default="", help="只启动指定部分，逗号分隔：mcp,agents,main"
    )
    parser.add_argument(
        "--mode",
        choices=["full", "local"],
        default="full",
        help="full=走 MCP+A2A；local=进程内直调（无需相关 SDK）",
    )
    args = parser.parse_args()

    setup_logging()
    print("=" * 72)
    print("智学 · 智慧教学问答与作业批改系统")
    print("=" * 72)
    ok, notes = check_environment()
    print("环境自检：")
    print("\n".join(notes))
    print("-" * 72)
    if args.check:
        return 0 if ok else 1

    if args.mode == "local":
        os.environ["ZHIXUE_TOOL_TRANSPORT"] = "local"
        os.environ["ZHIXUE_NETWORK_TRANSPORT"] = "local"
        print("local 模式：主应用会在进程内直接调用四个 Agent，无需 MCP/A2A SDK。")
        print("仍然只启动主应用一个进程；若要观察完整链路，请用 --mode full。")

    wanted = {x.strip() for x in args.only.split(",") if x.strip()}
    procs = [
        p
        for p in build_procs()
        if not wanted or p.kind in wanted or ("main" in wanted and p.kind == "main")
    ]
    if args.mode == "local":
        procs = [p for p in procs if p.kind == "main"]

    logs_dir = get_settings().log_dir
    logs_dir.mkdir(parents=True, exist_ok=True)

    running: list[tuple[Proc, subprocess.Popen]] = []
    children: list[subprocess.Popen] = []

    def shutdown(*_args) -> None:
        print("\n正在停止所有服务…")
        for proc in children:
            if proc.poll() is None:
                proc.terminate()
        deadline = time.time() + 10
        for proc in children:
            try:
                proc.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    try:
        signal.signal(signal.SIGTERM, shutdown)
    except (AttributeError, ValueError):  # pragma: no cover - Windows
        pass

    for proc in procs:
        log_path = logs_dir / f"{proc.module.split('.')[-1]}.out.log"
        handle = open(log_path, "a", encoding="utf-8")
        child = subprocess.Popen(
            proc.command(),
            stdout=handle,
            stderr=subprocess.STDOUT,
            cwd=str(get_settings().project_root),
            env={**os.environ},
        )
        children.append(child)
        running.append((proc, child))
        print(f"启动 {proc.name:<14} -> http://127.0.0.1:{proc.port}  (日志 {log_path.name})")

    print("-" * 72)
    print("等待主应用就绪…")
    if wait_for_http(get_settings().ports.main, timeout=40):
        print(f"\n智学已就绪： http://127.0.0.1:{get_settings().ports.main}")
        print("按 Ctrl+C 停止全部服务。\n")
    else:
        print("主应用启动超时，请查看 logs/ 下的日志。")

    try:
        while True:
            for proc, child in running:
                if child.poll() is not None:
                    print(f"[警告] {proc.name} 已退出（returncode={child.returncode}）")
            time.sleep(3)
    except KeyboardInterrupt:
        shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
