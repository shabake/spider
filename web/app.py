"""
Spider Web UI — FastAPI 后端 + SSE 实时流推送
"""

import asyncio
import json
import os
import sys
import uuid

# 确保项目根目录在 PYTHONPATH 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from core.agent import Agent
from core.llm import AuthError
from core.memory import MemoryStore
from core.sub_agent import SubAgentPool, DELEGATE_TASK_SCHEMA
from core.skill_manager import SkillManager, SAVE_SKILL_SCHEMA, LIST_SKILLS_SCHEMA
from core.mcp_client import MCPManager
from tools.shell import execute_shell, SHELL_TOOL_SCHEMA
from tools.read_write import read_file, write_file, list_files, READ_FILE_SCHEMA, WRITE_FILE_SCHEMA, LIST_FILES_SCHEMA
from tools.convert import docx_to_pdf, pdf_to_docx, DOCX_TO_PDF_SCHEMA, PDF_TO_DOCX_SCHEMA
from tools.web import web_search, web_fetch, WEB_SEARCH_SCHEMA, WEB_FETCH_SCHEMA
from tools.self_dev import (
    self_find, SELF_FIND_SCHEMA,
    self_map, SELF_MAP_SCHEMA,
    self_validate, SELF_VALIDATE_SCHEMA,
    self_review, SELF_REVIEW_SCHEMA,
    self_edit, SELF_EDIT_SCHEMA,
    self_commit, SELF_COMMIT_SCHEMA,
)

app = FastAPI(title="Spider Web UI")

# CORS — 开发时允许前端独立运行
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 全局 Agent 实例
_agent: Agent | None = None
_memory: MemoryStore | None = None
# Human-in-the-Loop 确认队列
_pending_confirms: dict[str, asyncio.Future] = {}


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = _create_agent()
    return _agent


def get_memory() -> MemoryStore:
    global _memory
    if _memory is None:
        _memory = MemoryStore()
    return _memory


def _create_agent():
    global _memory
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

    # 读取配置（从 app.state 或环境变量）
    strategy_mode = getattr(app.state, "strategy_mode", False) or os.environ.get("SPIDER_STRATEGY", "").lower() in ("1", "true", "yes")
    confirm_enabled = getattr(app.state, "confirm_enabled", True)
    plan_mode = getattr(app.state, "plan_mode", False)
    team_mode = getattr(app.state, "team_mode", False)
    profile = getattr(app.state, "profile", None)
    profile_name = getattr(app.state, "profile_name", None)
    if os.environ.get("SPIDER_NO_CONFIRM", "").lower() in ("1", "true", "yes"):
        confirm_enabled = False

    # 先创建 Agent（内部初始化 LLM），再用 LLM 初始化 MemoryStore
    agent = Agent(api_key=api_key, base_url=base_url, memory_store=None,
                  strategy_mode=strategy_mode, confirm_enabled=confirm_enabled,
                  plan_mode=plan_mode)
    agent.team_mode = team_mode

    # 应用 Profile 的 system prompt（提前设置，工具等所有工具注册完再处理）
    if profile and profile.get("prompt"):
        agent.set_system_prompt(profile["prompt"].strip())
    _memory = MemoryStore(llm=agent.llm)
    agent.memory = _memory
    agent.memory_store = _memory
    agent._register_memory_tools()

    # 子代理工具（注入 profile_loader）
    from main import load_profile
    sub_pool = SubAgentPool(
        api_key=api_key, base_url=base_url,
        tools=agent.tools, parent_agent=agent,
        profile_loader=load_profile,
    )
    agent.register_tool(
        "delegate_task",
        "将子任务交给独立的子 Agent 执行，可并行处理多个独立任务。"
        "适合: 同时查多个信息、独立子任务、需要隔离上下文的任务",
        sub_pool.delegate, DELEGATE_TASK_SCHEMA,
    )

    # 技能工具
    agent.register_tool(
        "save_skill",
        "将当前经验保存为可复用的技能。当你发现一个有效的任务解决方法时调用此工具。",
        agent.skill_manager.save, SAVE_SKILL_SCHEMA,
        risk_level="safe",
    )
    agent.register_tool(
        "list_skills",
        "列出所有已保存的技能",
        agent.skill_manager.list, LIST_SKILLS_SCHEMA,
        risk_level="safe",
    )

    # 内置工具
    agent.register_tool("shell", "执行 shell 命令（macOS/Linux）", execute_shell, SHELL_TOOL_SCHEMA,
                        risk_level="confirm")
    agent.register_tool("read_file", "读取文件内容", read_file, READ_FILE_SCHEMA,
                        risk_level="safe")
    agent.register_tool("write_file", "写入文件（会覆盖）", write_file, WRITE_FILE_SCHEMA,
                        risk_level="confirm")
    agent.register_tool("list_files", "列出目录内容", list_files, LIST_FILES_SCHEMA,
                        risk_level="safe")
    agent.register_tool("docx_to_pdf", "将 Word 文档 (.docx) 转换为 PDF", docx_to_pdf, DOCX_TO_PDF_SCHEMA,
                        risk_level="safe")
    agent.register_tool("pdf_to_docx", "将 PDF 转换为 Word 文档 (.docx)", pdf_to_docx, PDF_TO_DOCX_SCHEMA,
                        risk_level="safe")

    # ── 网络工具 ──────────────────────────────────────────
    agent.register_tool("web_search",
                        "搜索网络，返回相关网页标题和摘要。需要联网查资料时使用。",
                        web_search, WEB_SEARCH_SCHEMA, risk_level="safe")
    agent.register_tool("web_fetch",
                        "抓取指定 URL 的网页内容，提取可读文本。需要阅读具体网页时使用。",
                        web_fetch, WEB_FETCH_SCHEMA, risk_level="safe")

    # ── Self-Dev 工具 ──────────────────────────────────────
    agent.register_tool(
        "self_find",
        "【自开发】在 Spider 自己的源码中语义搜索代码。"
        "传入自然语言描述，找到对应的函数、类、变量位置。",
        self_find, SELF_FIND_SCHEMA,
        risk_level="safe",
    )
    agent.register_tool(
        "self_map",
        "【自开发】查看 Spider 自己的项目结构。"
        "了解有哪些模块、每个文件负责什么。开发新功能前先看这个。",
        self_map, SELF_MAP_SCHEMA,
        risk_level="safe",
    )
    agent.register_tool(
        "self_validate",
        "【自开发】验证 Python 文件的语法正确性。修改代码后使用。",
        self_validate, SELF_VALIDATE_SCHEMA,
        risk_level="safe",
    )
    agent.register_tool(
        "self_review",
        "【自开发】审查当前的 git 代码变更。修改代码后提交前使用。",
        self_review, SELF_REVIEW_SCHEMA,
        risk_level="safe",
    )
    agent.register_tool(
        "self_edit",
        "【自开发】安全地修改代码文件。自动备份→替换→语法验证→失败回滚。",
        self_edit, SELF_EDIT_SCHEMA,
        risk_level="confirm",
    )
    agent.register_tool(
        "self_commit",
        "【自开发】自动提交代码变更到 git。自动 add→commit。",
        self_commit, SELF_COMMIT_SCHEMA,
        risk_level="confirm",
    )

    # MCP 服务器（从 mcp_servers.json 加载）
    mcp_config = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp_servers.json")
    if os.path.exists(mcp_config):
        agent.mcp_manager = MCPManager(config_path=mcp_config)

    # 应用 Profile 的工具白名单和风险覆盖（在所有工具注册完后）
    if profile:
        prof_tools = profile.get("tools", None)
        prof_overrides = profile.get("risk_overrides", {}) or {}
        if prof_tools is not None:
            for name in list(agent.tools.names):
                if name not in prof_tools:
                    agent.tools._tools.pop(name, None)
        for tool_name, risk in prof_overrides.items():
            try:
                agent.tools.set_risk_override(tool_name, risk)
            except Exception:
                pass

    return agent


# ── SSE 事件推送 ──────────────────────────────────────────

async def event_stream(task: str):
    """SSE 事件流生成器"""
    agent = get_agent()
    event_queue = asyncio.Queue()

    # 构建回调
    async def on_thinking_chunk(chunk: str):
        await event_queue.put(("thinking_chunk", chunk))

    async def on_thinking_done(content: str):
        await event_queue.put(("thinking_done", content))

    async def on_turn_start(turn: int, max_turns: int):
        await event_queue.put(("turn_start", json.dumps({"turn": turn, "max_turns": max_turns}, ensure_ascii=False)))

    async def on_tool_call(name: str, arguments: dict):
        await event_queue.put(("tool_call", json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False)))

    async def on_tool_result(name: str, result: str):
        truncated = result[:2000]
        await event_queue.put(("tool_result", json.dumps({"name": name, "result": truncated}, ensure_ascii=False)))

    async def on_confirm(message: str) -> bool:
        """发送确认请求给前端，等待用户响应"""
        confirm_id = str(uuid.uuid4())[:8]
        future = asyncio.get_event_loop().create_future()
        _pending_confirms[confirm_id] = future
        await event_queue.put(("confirm", json.dumps({"message": message, "id": confirm_id}, ensure_ascii=False)))
        try:
            result = await asyncio.wait_for(future, timeout=120)
            return result
        except asyncio.TimeoutError:
            _pending_confirms.pop(confirm_id, None)
            return False

    async def on_done(content: str, elapsed: str):
        await event_queue.put(("done", json.dumps({"content": content, "elapsed": elapsed}, ensure_ascii=False)))
        await event_queue.put(None)  # 结束信号

    async def on_error(msg: str):
        await event_queue.put(("error", msg))

    on_event = {
        "thinking_chunk": on_thinking_chunk,
        "thinking_done": on_thinking_done,
        "turn_start": on_turn_start,
        "tool_call": on_tool_call,
        "tool_result": on_tool_result,
        "done": on_done,
        "error": on_error,
        "confirm": on_confirm,
    }

    # 后台运行 agent
    async def run_agent():
        try:
            await agent.run(task, stream=True, on_event=on_event)
        except AuthError as e:
            await event_queue.put(("error", str(e)))
            await event_queue.put(None)
        except Exception as e:
            await event_queue.put(("error", f"Agent 运行出错: {e}"))
            await event_queue.put(None)

    # 启动 agent 任务
    agent_task = asyncio.create_task(run_agent())

    try:
        while True:
            item = await event_queue.get()
            if item is None:
                break
            event_type, data = item
            yield f"event: {event_type}\ndata: {data}\n\n"
    finally:
        agent_task.cancel()
        try:
            await agent_task
        except asyncio.CancelledError:
            pass


# ── API 路由 ──────────────────────────────────────────────

@app.get("/")
async def index():
    """渲染主页面"""
    html_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Spider Web UI</h1><p>模板文件未找到</p>")


@app.post("/api/chat/stream")
async def chat_stream(body: dict):
    """SSE 流式聊天接口"""
    task = body.get("task", "").strip()
    if not task:
        return JSONResponse({"error": "任务不能为空"}, status_code=400)
    return StreamingResponse(
        event_stream(task),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chat/confirm")
async def confirm_action(body: dict):
    """Human-in-the-Loop: 用户确认/拒绝"""
    confirm_id = body.get("confirm_id", "")
    approved = body.get("approved", False)
    future = _pending_confirms.get(confirm_id)
    if future:
        future.set_result(approved)
        _pending_confirms.pop(confirm_id, None)
        return {"status": "ok", "approved": approved}
    return JSONResponse({"error": "确认请求已过期"}, status_code=404)


@app.get("/api/conversations")
async def list_conversations(limit: int = 20):
    """列出最近对话"""
    memory = get_memory()
    result = await memory.list_conversations(limit=limit)
    # 转成 JSON 格式
    import sqlite3
    conn = memory._get_conn()
    rows = conn.execute(
        "SELECT id, summary, turn_count, created_at FROM conversations "
        "ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {"id": r["id"], "summary": r["summary"], "turn_count": r["turn_count"], "created_at": r["created_at"]}
        for r in rows
    ]


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: int):
    """获取单条对话详情"""
    memory = get_memory()
    conn = memory._get_conn()
    conv = conn.execute(
        "SELECT * FROM conversations WHERE id = ?", (conv_id,)
    ).fetchone()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    messages = conn.execute(
        "SELECT role, content, metadata, created_at FROM messages "
        "WHERE conversation_id = ? ORDER BY id", (conv_id,)
    ).fetchall()
    return {
        "id": conv["id"],
        "summary": conv["summary"],
        "turn_count": conv["turn_count"],
        "created_at": conv["created_at"],
        "updated_at": conv["updated_at"],
        "messages": [
            {
                "role": r["role"],
                "content": (r["content"] or "")[:5000],
                "metadata": json.loads(r["metadata"] or "{}"),
                "created_at": r["created_at"],
            }
            for r in messages
        ],
    }


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: int):
    """删除对话"""
    memory = get_memory()
    conn = memory._get_conn()
    conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    conn.commit()
    return {"status": "ok"}


@app.get("/api/tools")
async def list_tools():
    """列出可用工具"""
    agent = get_agent()
    return [
        {"name": name, "schema": agent.tools.get(name).schema}
        for name in agent.tools.names
    ]


@app.get("/api/status")
async def status():
    """检查 API Key 和系统状态"""
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    strategy_mode = getattr(app.state, "strategy_mode", False) or os.environ.get("SPIDER_STRATEGY", "").lower() in ("1", "true", "yes")
    confirm_enabled = getattr(app.state, "confirm_enabled", True)
    plan_mode = getattr(app.state, "plan_mode", False)
    team_mode = getattr(app.state, "team_mode", False)
    profile_name = getattr(app.state, "profile_name", None)
    if os.environ.get("SPIDER_NO_CONFIRM", "").lower() in ("1", "true", "yes"):
        confirm_enabled = False
    return {
        "api_key_configured": bool(api_key),
        "api_key_prefix": api_key[:8] + "..." if api_key else "",
        "memory_db": get_memory().db_path if get_memory() else None,
        "strategy_mode": strategy_mode,
        "confirm_enabled": confirm_enabled,
        "plan_mode": plan_mode,
        "team_mode": team_mode,
        "profile": profile_name,
    }
