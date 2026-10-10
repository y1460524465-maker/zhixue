"""智学主应用（main.py :8000）。

对应架构图上半部分：

    用户输入 -> LLM Router 意图识别
                 ├─ 信息缺失 -> 询问用户（回到用户输入）
                 └─ 信息完整 -> AgentNetwork -> 各 Agent

    各 Agent 结果 -> 结果优化（LLM 总结）-> 用户界面展示

隔离与记忆的三条约定在这里落地：

1. **身份只在入口解析一次**：登录态 -> ``user_id``，之后随任务包一路传下去；
2. **存储访问强制带身份**：会话、草稿、文件全部按 ``user_id`` 过滤；
3. **身份缺失直接拒绝**：不给默认用户，降级可以用于功能，不能用于权限。
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from zhixue.app.agent_network import AgentNetwork
from zhixue.app.qa import answer_question
from zhixue.app.router_agent import LLMRouter
from zhixue.app.summarizer import ResultSummarizer
from zhixue.auth import ROLE_STUDENT, authenticate, create_token, decode_token
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
    description="多 Agent 协同：教案生成 / 出题 / 批改 / 学情分析",
    version="1.1.0",
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
# 身份
# --------------------------------------------------------------------------- #
def current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """从 Authorization 头解析身份。

    令牌只在入口解析一次；之后各层用这个 ``user_id`` 过滤数据，
    绝不重新解析、也不从任何全局变量取。
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少登录凭证")
    payload = decode_token(authorization.split(" ", 1)[1].strip())
    if not payload:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return payload


def _user_dir(user_id: str) -> str:
    """每个用户一个目录名（文件层的隔离点）。"""
    safe = "".join(ch for ch in (user_id or "") if ch.isalnum() or ch in "-_")
    return safe or "anonymous"


def _resolve_student(user: dict[str, Any], request: ChatRequest) -> str | None:
    """决定这次对话谈的是哪个学生的数据。

    学生账号被**强制**绑定到自己的学号——请求里传什么都改不了，
    这是隔离的硬约束。老师账号则由对话内容决定（路由器从话里抽学号）。
    """
    if user.get("role") == ROLE_STUDENT:
        sid = user.get("sid") or ""
        if not sid:
            raise HTTPException(status_code=403, detail="该学生账号未绑定学号，请联系管理员")
        return sid
    return request.student_id or None


# --------------------------------------------------------------------------- #
# 会话历史
# --------------------------------------------------------------------------- #
def _save_conversation(
    user_id: str,
    session_id: str,
    student_id: str | None,
    question: str,
    answer: str,
    intent: str,
) -> None:
    try:
        get_mysql().execute(
            "INSERT INTO conversation "
            "(session_id, user_id, student_id, question, answer, intent, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                session_id, user_id, student_id, question, answer, intent,
                time.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
    except StoreUnavailable as exc:
        logger.warning("会话历史写入失败: %s", exc)


def _load_history(user_id: str, session_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """只返回**属于这个用户**的历史（隔离点）。"""
    try:
        rows = get_mysql().query(
            "SELECT question, answer, intent, created_at FROM conversation "
            "WHERE session_id = %s AND user_id = %s ORDER BY id DESC LIMIT %s",
            (session_id, user_id, limit),
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
# 登录
# --------------------------------------------------------------------------- #
@app.post("/api/login")
async def login(payload: dict[str, Any]) -> dict[str, Any]:
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="请输入用户名和密码")
    try:
        user = authenticate(get_mysql(), username, password)
    except StoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"数据库不可用: {exc}") from exc
    if not user:
        # 不区分"用户不存在"和"密码错误"，避免账号枚举
        raise HTTPException(status_code=401, detail="用户名或密码不正确")
    logger.info("用户登录: %s (%s)", user["username"], user["role"])
    return {"token": create_token(user), "user": user}


@app.get("/api/me")
async def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {
        "user_id": user["uid"],
        "role": user["role"],
        "name": user.get("name", ""),
        "student_id": user.get("sid") or None,
    }


# --------------------------------------------------------------------------- #
# 核心接口
# --------------------------------------------------------------------------- #
async def _handle(request: ChatRequest, user: dict[str, Any]) -> ChatResponse:
    started = time.time()
    user_id = user["uid"]
    session_id = request.session_id or uuid.uuid4().hex[:12]
    set_task_id(uuid.uuid4().hex)
    student_id = _resolve_student(user, request)
    logger.info("用户 %s 会话 %s 输入: %s", user_id, session_id, request.message)

    # 1) 意图识别 + 槽位填充（草稿按 user 隔离）
    decision: RouterDecision = router.route(
        request.message, session_id=session_id, student_id=student_id, user_id=user_id
    )
    if request.upload_paths:
        decision.slots.setdefault("file_path", request.upload_paths[0])
    decision.slots["session_id"] = session_id

    # 2) 闲聊直接回
    if decision.intent is Intent.CHITCHAT:
        reply = _chitchat_reply(request.message)
        _save_conversation(user_id, session_id, student_id, request.message, reply, decision.intent.value)
        return ChatResponse(
            session_id=session_id, type="answer", text=reply,
            intent=decision.intent, slots=decision.slots,
            elapsed=round(time.time() - started, 2),
        )

    # 3) 信息缺失 -> 询问用户（流程回到"用户输入"）
    if decision.missing:
        _save_conversation(
            user_id, session_id, student_id, request.message, decision.reply, "ask_user"
        )
        return ChatResponse(
            session_id=session_id, type="ask_user", text=decision.reply,
            intent=decision.intent, slots=decision.slots, missing=decision.missing,
            elapsed=round(time.time() - started, 2),
        )

    # 3.5) 课本答疑：没有对应 Agent，由主应用直接走 RAG
    if decision.intent is Intent.TEXTBOOK_QA:
        text, data, _refs = answer_question(
            str(decision.slots.get("question") or request.message),
            subject=decision.slots.get("subject"),
        )
        router.reset(session_id, user_id)
        _save_conversation(user_id, session_id, student_id, request.message, text, decision.intent.value)
        return ChatResponse(
            session_id=session_id, type="answer", text=text,
            intent=decision.intent, slots=decision.slots,
            cards=[{"type": "qa", **data}], agents=["main.rag"],
            elapsed=round(time.time() - started, 2),
        )

    router.reset(session_id, user_id)  # 槽位已用完，清掉草稿

    # 4) 信息完整 -> AgentNetwork（身份随任务包传递）
    results = await network.dispatch(decision, user_id=user_id)

    # 5) 结果优化 - LLM 总结
    response = summarizer.build_response(
        session_id, decision, results, round(time.time() - started, 2)
    )
    _save_conversation(user_id, session_id, student_id, request.message, response.text, decision.intent.value)
    return response


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user: dict[str, Any] = Depends(current_user)) -> ChatResponse:
    """主对话接口（需要登录）。"""
    return await _handle(request, user)


@app.post("/api/chat/stream")
async def chat_stream(
    request: ChatRequest, user: dict[str, Any] = Depends(current_user)
) -> StreamingResponse:
    """流式版本：先推路由结果，再推正文与卡片，最后推 end。"""
    user_id = user["uid"]

    async def event_source():
        started = time.time()
        session_id = request.session_id or uuid.uuid4().hex[:12]
        set_task_id(uuid.uuid4().hex)
        student_id = _resolve_student(user, request)
        decision = router.route(
            request.message, session_id=session_id, student_id=student_id, user_id=user_id
        )
        if request.upload_paths:
            decision.slots.setdefault("file_path", request.upload_paths[0])
        decision.slots["session_id"] = session_id

        yield _sse("route", {
            "session_id": session_id, "intent": decision.intent.value,
            "missing": decision.missing, "slots": decision.slots,
        })

        if decision.intent is Intent.CHITCHAT or decision.missing:
            text = _chitchat_reply(request.message) if decision.intent is Intent.CHITCHAT else decision.reply
            _save_conversation(
                user_id, session_id, student_id, request.message, text,
                "ask_user" if decision.missing else decision.intent.value,
            )
            yield _sse("token", {"text": text})
            yield _sse("end", {
                "session_id": session_id,
                "type": "ask_user" if decision.missing else "answer",
                "elapsed": round(time.time() - started, 2),
            })
            return

        if decision.intent is Intent.TEXTBOOK_QA:
            text, data, _refs = answer_question(
                str(decision.slots.get("question") or request.message),
                subject=decision.slots.get("subject"),
            )
            for char in text:
                yield _sse("token", {"text": char})
            yield _sse("card", {"type": "qa", **data})
            router.reset(session_id, user_id)
            _save_conversation(user_id, session_id, student_id, request.message, text, decision.intent.value)
            yield _sse("end", {
                "session_id": session_id, "type": "answer",
                "elapsed": round(time.time() - started, 2),
            })
            return

        router.reset(session_id, user_id)
        for agent, _job in network.plan(decision, user_id=user_id):
            yield _sse("agent", {"agent": agent, "status": "running"})

        results = await network.dispatch(decision, user_id=user_id)
        response = summarizer.build_response(
            session_id, decision, results, round(time.time() - started, 2)
        )
        for char in response.text:
            yield _sse("token", {"text": char})
        for card in response.cards:
            yield _sse("card", card)
        _save_conversation(user_id, session_id, student_id, request.message, response.text, decision.intent.value)
        yield _sse("end", {
            "session_id": session_id, "type": response.type, "elapsed": response.elapsed,
        })

    return StreamingResponse(event_source(), media_type="text/event-stream")


def _sse(event: str, payload: dict[str, Any]) -> str:
    import json as _json

    return f"event: {event}\ndata: {_json.dumps(payload, ensure_ascii=False)}\n\n"


def _chitchat_reply(message: str) -> str:
    text = message or ""
    if any(word in text for word in ("你是谁", "你叫什么", "什么系统")):
        return "我是「智学」，一个由教案生成、出题、作业批改、学情分析四个 Agent 协同的智慧教学助手。"
    if "谢谢" in text:
        return "不客气！继续加油，有任何学习问题随时问我。"
    return "你好！我是「智学」。你可以让我：出题、批改作业、分析学情、生成教案或学习计划。"


# --------------------------------------------------------------------------- #
# 辅助接口
# --------------------------------------------------------------------------- #
@app.get("/api/students")
async def students(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """学生账号只能看到自己；老师账号可以看到全部。"""
    try:
        if user.get("role") == ROLE_STUDENT:
            sid = user.get("sid") or ""
            rows = get_mysql().query(
                "SELECT student_id, name, class_name FROM student WHERE student_id = %s", (sid,)
            )
        else:
            rows = get_mysql().query(
                "SELECT student_id, name, class_name FROM student ORDER BY student_id"
            )
    except StoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"数据库不可用: {exc}") from exc
    return {"students": [dict(r) for r in rows]}


@app.get("/api/homeworks")
async def homeworks(
    subject: str | None = None, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
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
async def agents(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {
        "transport": network.transport,
        "tool_transport": settings.tool_transport,
        "agents": network.status(),
    }


@app.get("/api/retrieval")
async def retrieval_status(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    from zhixue.vector import get_retriever

    return get_retriever().status()


@app.get("/api/session/{session_id}")
async def session_history(
    session_id: str, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    """只能读自己的会话——别人的 session_id 也读不到内容。"""
    return {
        "session_id": session_id,
        "history": _load_history(user["uid"], session_id, limit=20),
    }


@app.delete("/api/session/{session_id}")
async def clear_session(
    session_id: str, user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    try:
        get_mysql().execute(
            "DELETE FROM conversation WHERE session_id = %s AND user_id = %s",
            (session_id, user["uid"]),
        )
    except StoreUnavailable:
        pass
    router.reset(session_id, user["uid"])
    return {"status": "ok", "session_id": session_id}


@app.post("/api/upload")
async def upload(
    file: UploadFile = File(...), user: dict[str, Any] = Depends(current_user)
) -> dict[str, Any]:
    """上传答题卡图片；文件按用户分目录存放。"""
    suffix = Path(file.filename or "upload.png").suffix or ".png"
    name = f"upload_{uuid.uuid4().hex[:8]}{suffix}"
    target = settings.upload_dir / _user_dir(user["uid"])
    target.mkdir(parents=True, exist_ok=True)
    path = target / name
    path.write_bytes(await file.read())
    logger.info("用户 %s 上传文件: %s", user["uid"], path)
    return {"filename": name, "path": str(path), "url": f"/api/files/{name}"}


@app.get("/api/files/{filename}")
async def download(
    filename: str, user: dict[str, Any] = Depends(current_user)
) -> FileResponse:
    """下载文件；只在自己的目录里找，找不到再退化到公共模板目录。"""
    safe = Path(filename).name
    mine = _user_dir(user["uid"])
    candidates = [
        settings.output_dir / mine / safe,
        settings.upload_dir / mine / safe,
        settings.template_dir / safe,  # 模板是公共资源，人人可下
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return FileResponse(str(candidate), filename=safe)
    raise HTTPException(status_code=404, detail=f"文件不存在: {safe}")


@app.get("/api/templates")
async def templates(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
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
