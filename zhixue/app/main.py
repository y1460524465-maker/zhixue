"""智学主应用（main.py :8000）。

对应架构图上半部分：

    用户输入 -> LLM Router 意图识别
                 ├─ 信息缺失 -> 询问用户（回到用户输入）
                 └─ 信息完整 -> AgentNetwork -> 各 Agent

    各 Agent 结果 -> 结果优化（LLM 总结）-> 用户界面展示
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from zhixue.app.agent_network import AgentNetwork
from zhixue.app.qa import answer_question
from zhixue.app.router_agent import LLMRouter
from zhixue.app.summarizer import ResultSummarizer
from zhixue.config import get_settings
from zhixue.logging_setup import get_logger, set_task_id, setup_logging
from zhixue.schemas import ChatRequest, ChatResponse, Intent, RouterDecision
from zhixue.store import StoreUnavailable, get_mysql

logger = get_logger("app.main")

settings = get_settings()
router = LLMRouter()
network = AgentNetwork()
summarizer = ResultSummarizer()

app = FastAPI(
    title="智学 · 智慧教学问答与作业批改系统",
    description="多 Agent 协同：文档生成 / 出题 / 批改 / 学情分析",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings.static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")


# --------------------------------------------------------------------------- #
# 会话历史
# --------------------------------------------------------------------------- #
def _save_conversation(session_id: str, student_id: str | None, question: str, answer: str, intent: str) -> None:
    try:
        mysql = get_mysql()
        mysql.execute(
            "INSERT INTO conversation (session_id, student_id, question, answer, intent, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                session_id,
                student_id,
                question,
                answer,
                intent,
                time.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
    except StoreUnavailable as exc:
        logger.warning("会话历史写入失败: %s", exc)


def _load_history(session_id: str, limit: int = 5) -> list[dict[str, Any]]:
    try:
        rows = get_mysql().query(
            "SELECT question, answer, intent, created_at FROM conversation "
            "WHERE session_id = %s ORDER BY id DESC LIMIT %s",
            (session_id, limit),
        )
    except StoreUnavailable:
        return []
    return list(reversed([dict(r) for r in rows]))


# --------------------------------------------------------------------------- #
# 页面
# --------------------------------------------------------------------------- #
@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    index_file = settings.static_dir / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="前端页面尚未生成")
    return FileResponse(str(index_file))


# --------------------------------------------------------------------------- #
# 核心接口
# --------------------------------------------------------------------------- #
async def _handle(request: ChatRequest) -> ChatResponse:
    started = time.time()
    session_id = request.session_id or uuid.uuid4().hex[:12]
    task_id = uuid.uuid4().hex
    set_task_id(task_id)
    logger.info("会话 %s 收到输入: %s", session_id, request.message)

    # 1) 意图识别 + 槽位填充
    decision: RouterDecision = router.route(
        request.message, session_id=session_id, student_id=request.student_id
    )
    if request.upload_paths:
        decision.slots.setdefault("file_path", request.upload_paths[0])
    decision.slots["session_id"] = session_id

    # 2) 闲聊直接回
    if decision.intent is Intent.CHITCHAT:
        reply = _chitchat_reply(request.message)
        _save_conversation(session_id, request.student_id, request.message, reply, decision.intent.value)
        return ChatResponse(
            session_id=session_id,
            type="answer",
            text=reply,
            intent=decision.intent,
            slots=decision.slots,
            elapsed=round(time.time() - started, 2),
        )

    # 3) 信息缺失 -> 询问用户（流程回到"用户输入"）
    if decision.missing:
        _save_conversation(
            session_id, request.student_id, request.message, decision.reply, "ask_user"
        )
        return ChatResponse(
            session_id=session_id,
            type="ask_user",
            text=decision.reply,
            intent=decision.intent,
            slots=decision.slots,
            missing=decision.missing,
            elapsed=round(time.time() - started, 2),
        )

    # 3.5) 课本答疑：没有对应 Agent，由主应用直接走 RAG
    if decision.intent is Intent.TEXTBOOK_QA:
        text, data, _refs = answer_question(
            str(decision.slots.get("question") or request.message),
            subject=decision.slots.get("subject"),
        )
        router.reset(session_id)
        _save_conversation(
            session_id, request.student_id, request.message, text, decision.intent.value
        )
        return ChatResponse(
            session_id=session_id,
            type="answer",
            text=text,
            intent=decision.intent,
            slots=decision.slots,
            cards=[{"type": "qa", **data}],
            agents=["main.rag"],
            elapsed=round(time.time() - started, 2),
        )

    router.reset(session_id)  # 槽位已经用完，清掉草稿

    # 4) 信息完整 -> AgentNetwork
    results = await network.dispatch(decision)

    # 5) 结果优化 - LLM 总结
    response = summarizer.build_response(
        session_id, decision, results, round(time.time() - started, 2)
    )
    _save_conversation(
        session_id, request.student_id, request.message, response.text, decision.intent.value
    )
    return response


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """主对话接口。"""
    return await _handle(request)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """流式版本：先推路由结果，再推正文与卡片，最后推 end。"""
    import json as _json

    async def event_source():
        started = time.time()
        session_id = request.session_id or uuid.uuid4().hex[:12]
        set_task_id(uuid.uuid4().hex)
        decision = router.route(
            request.message, session_id=session_id, student_id=request.student_id
        )
        if request.upload_paths:
            decision.slots.setdefault("file_path", request.upload_paths[0])
        decision.slots["session_id"] = session_id

        yield _sse("route", {"session_id": session_id, "intent": decision.intent.value,
                             "missing": decision.missing, "slots": decision.slots})

        if decision.intent is Intent.CHITCHAT or decision.missing:
            text = _chitchat_reply(request.message) if decision.intent is Intent.CHITCHAT else decision.reply
            _save_conversation(
                session_id, request.student_id, request.message, text,
                "ask_user" if decision.missing else decision.intent.value,
            )
            yield _sse("token", {"text": text})
            yield _sse("end", {"session_id": session_id, "type": "ask_user" if decision.missing else "answer",
                               "elapsed": round(time.time() - started, 2)})
            return

        if decision.intent is Intent.TEXTBOOK_QA:
            text, data, _refs = answer_question(
                str(decision.slots.get("question") or request.message),
                subject=decision.slots.get("subject"),
            )
            for char in text:
                yield _sse("token", {"text": char})
            yield _sse("card", {"type": "qa", **data})
            router.reset(session_id)
            _save_conversation(
                session_id, request.student_id, request.message, text, decision.intent.value
            )
            yield _sse("end", {"session_id": session_id, "type": "answer",
                               "elapsed": round(time.time() - started, 2)})
            return

        router.reset(session_id)
        for agent, _job in network.plan(decision):
            yield _sse("agent", {"agent": agent, "status": "running"})

        results = await network.dispatch(decision)
        response = summarizer.build_response(
            session_id, decision, results, round(time.time() - started, 2)
        )
        for char in response.text:
            yield _sse("token", {"text": char})
        for card in response.cards:
            yield _sse("card", card)
        _save_conversation(
            session_id, request.student_id, request.message, response.text, decision.intent.value
        )
        yield _sse("end", {"session_id": session_id, "type": response.type,
                           "elapsed": response.elapsed})

    return StreamingResponse(event_source(), media_type="text/event-stream")


def _sse(event: str, payload: dict[str, Any]) -> str:
    import json as _json

    return f"event: {event}\ndata: {_json.dumps(payload, ensure_ascii=False)}\n\n"


def _chitchat_reply(message: str) -> str:
    text = message or ""
    if any(word in text for word in ("你是谁", "你叫什么", "什么系统")):
        return "我是「智学」，一个由文档生成、出题、作业批改、学情分析四个 Agent 协同的智慧教学助手。"
    if "谢谢" in text:
        return "不客气！继续加油，有任何学习问题随时问我。"
    return "你好！我是「智学」。你可以让我：出题、批改作业、分析学情、生成讲义或学习计划。"


# --------------------------------------------------------------------------- #
# 辅助接口
# --------------------------------------------------------------------------- #
@app.get("/api/students")
async def students() -> dict[str, Any]:
    return {"students": router.list_students()}


@app.get("/api/homeworks")
async def homeworks(subject: str | None = None) -> dict[str, Any]:
    sql = "SELECT homework_id, title, subject, kp_id, full_score, publish_time FROM homework"
    params: tuple[Any, ...] = ()
    if subject:
        sql += " WHERE subject = %s"
        params = (subject,)
    sql += " ORDER BY homework_id"
    try:
        rows = [dict(r) for r in get_mysql().query(sql, params)]
    except StoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"数据库不可用: {exc}") from exc
    return {"homeworks": rows}


@app.get("/api/agents")
async def agents() -> dict[str, Any]:
    return {
        "transport": network.transport,
        "tool_transport": settings.tool_transport,
        "agents": network.status(),
    }


@app.get("/api/retrieval")
async def retrieval_status() -> dict[str, Any]:
    from zhixue.vector import get_retriever

    return get_retriever().status()


@app.get("/api/session/{session_id}")
async def session_history(session_id: str) -> dict[str, Any]:
    return {"session_id": session_id, "history": _load_history(session_id, limit=20)}


@app.delete("/api/session/{session_id}")
async def clear_session(session_id: str) -> dict[str, Any]:
    try:
        get_mysql().execute("DELETE FROM conversation WHERE session_id = %s", (session_id,))
    except StoreUnavailable:
        pass
    router.reset(session_id)
    return {"status": "ok", "session_id": session_id}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    """上传答题卡图片，返回可用于批改的绝对路径。"""
    suffix = Path(file.filename or "upload.png").suffix or ".png"
    name = f"upload_{uuid.uuid4().hex[:8]}{suffix}"
    path = settings.upload_dir / name
    path.write_bytes(await file.read())
    logger.info("收到上传文件: %s", path)
    return {"filename": name, "path": str(path), "url": f"/api/files/{name}"}


@app.get("/api/files/{filename}")
async def download(filename: str) -> FileResponse:
    """下载 Agent 生成的文档 / 上传的图片。"""
    safe = Path(filename).name
    for folder in (settings.output_dir, settings.upload_dir, settings.template_dir):
        candidate = folder / safe
        if candidate.exists() and candidate.is_file():
            return FileResponse(str(candidate), filename=safe)
    raise HTTPException(status_code=404, detail=f"文件不存在: {safe}")


@app.get("/api/templates")
async def templates() -> dict[str, Any]:
    from zhixue.tools.docgen_tools import list_templates

    return {"templates": list_templates()}


@app.get("/health")
@app.get("/api/health")
async def health() -> dict[str, Any]:
    mysql_ok = False
    try:
        mysql_ok = get_mysql().ping()
    except Exception:  # noqa: BLE001
        mysql_ok = False
    return {
        "status": "healthy",
        "app": settings.app_name,
        "mysql": mysql_ok,
        "network_transport": network.transport,
        "tool_transport": settings.tool_transport,
    }


@app.exception_handler(StoreUnavailable)
async def store_error(_request, exc: StoreUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": f"数据库不可用: {exc}"})


def main() -> None:
    import uvicorn

    setup_logging()
    logger.info("启动智学主应用 -> http://%s:%d", settings.host, settings.ports.main)
    uvicorn.run(app, host=settings.host, port=settings.ports.main, log_level="info")


if __name__ == "__main__":
    main()
