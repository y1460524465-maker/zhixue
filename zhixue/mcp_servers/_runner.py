"""MCP Server 的统一启动器。

单独抽出来是为了两件事：

1. ``fastmcp`` 只在真正要起服务时才 import，
   这样业务代码和单测完全不依赖它；
2. 端口 / 路径 / 绑定地址统一走 :mod:`zhixue.config`。
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from zhixue.config import get_settings
from zhixue.logging_setup import get_logger, setup_logging

logger = get_logger("mcp.runner")


def build_server(name: str, instructions: str, register: Callable[[Any], None]) -> Any:
    """创建 FastMCP 实例并注册工具。"""
    try:
        from fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - 取决于运行环境
        raise SystemExit(
            "缺少 fastmcp，无法启动 MCP 服务。\n"
            "安装： pip install fastmcp\n"
            "（若暂时不想装，可把 config.ini 的 zhixue.tool_transport 设为 local，"
            "Agent 会直接在进程内调用这些工具。）"
        ) from exc

    mcp = FastMCP(name=name, instructions=instructions)
    register(mcp)
    tool_names = sorted(getattr(t, "name", str(t)) for t in mcp._tool_manager.list_tools()) \
        if hasattr(mcp, "_tool_manager") else []
    logger.info("MCP Server [%s] 已注册工具 %s", name, tool_names or "(见启动日志)")
    return mcp


def parse_common_args(service: str, default_port: int) -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=f"智学 {service} MCP Server")
    parser.add_argument("--host", default=settings.host, help="绑定地址")
    parser.add_argument("--port", type=int, default=default_port, help="监听端口")
    parser.add_argument("--path", default=settings.ports.mcp_path, help="MCP 端点路径")
    return parser.parse_args()


def serve(
    service: str,
    name: str,
    instructions: str,
    register: Callable[[Any], None],
    default_port: int,
) -> None:
    """启动一个 MCP Server（阻塞）。"""
    setup_logging()
    args = parse_common_args(service, default_port)
    mcp = build_server(name, instructions, register)
    logger.info(
        "启动 %s：http://%s:%d%s （streamable HTTP）", service, args.host, args.port, args.path
    )
    mcp.run(transport="http", host=args.host, port=args.port, path=args.path)


__all__ = ["build_server", "serve", "parse_common_args"]
