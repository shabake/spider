#!/usr/bin/env python3
"""
Spider — 轻量级 Agent 系统 (仿 Hermes 设计模式)

用法:
    python main.py "你的任务"
    python main.py --interactive
    python main.py --web
"""

import argparse
import asyncio
import logging
import os
import sys
import random

# 确保项目根目录在 PYTHONPATH 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.agent import Agent
from core.llm import AuthError
from core.memory import MemoryStore
from core.sub_agent import SubAgentPool, DELEGATE_TASK_SCHEMA
from core.skill_manager import SkillManager, SAVE_SKILL_SCHEMA, LIST_SKILLS_SCHEMA
from core.mcp_client import MCPManager
from core.cli import SpiderCLI
from tools.shell import execute_shell, SHELL_TOOL_SCHEMA
from tools.read_write import read_file, write_file, list_files, READ_FILE_SCHEMA, WRITE_FILE_SCHEMA, LIST_FILES_SCHEMA
from tools.convert import docx_to_pdf, pdf_to_docx, DOCX_TO_PDF_SCHEMA, PDF_TO_DOCX_SCHEMA
from tools.web import web_search, web_fetch, WEB_SEARCH_SCHEMA, WEB_FETCH_SCHEMA
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from tools.self_dev import (
    self_find, SELF_FIND_SCHEMA,
    self_map, SELF_MAP_SCHEMA,
    self_validate, SELF_VALIDATE_SCHEMA,
    self_review, SELF_REVIEW_SCHEMA,
    self_edit, SELF_EDIT_SCHEMA,
    self_commit, SELF_COMMIT_SCHEMA,
)

logging.basicConfig(level=logging.WARNING)

cli = SpiderCLI()


# ── Profile 系统 ────────────────────────────────────────────

def load_profile(name: str) -> dict | None:
    """加载 profiles/ 下的角色配置文件

    Args:
        name: 角色名（对应 profiles/{name}.yaml）

    Returns:
        解析后的 dict，或 None（文件不存在时）
    """
    import os
    fpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles", f"{name}.yaml")
    if not os.path.exists(fpath):
        print(f"⚠️  Profile '{name}' 不存在 (profiles/{name}.yaml)")
        return None

    if HAS_YAML:
        with open(fpath, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    # fallback: 简易解析
    return _load_yaml_simple(fpath)


def _load_yaml_simple(fpath: str) -> dict:
    """简易 YAML 解析（不依赖 pyyaml）"""
    data = {}
    current_key = None
    current_lines = []
    with open(fpath, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.rstrip()
            if not stripped or stripped.startswith("#"):
                continue
            if not stripped[0].isspace():
                if current_key:
                    data[current_key] = "\n".join(current_lines).strip() if current_lines else ""
                    current_lines = []
                if ":" in stripped:
                    key, _, val = stripped.partition(":")
                    current_key = key.strip()
                    val = val.strip()
                    if val:
                        # 列表值: [a, b, c]
                        if val.startswith("[") and val.endswith("]"):
                            data[current_key] = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",") if v.strip()]
                        else:
                            data[current_key] = val
                        current_key = None
            elif current_key and stripped:
                current_lines.append(stripped)
        if current_key:
            data[current_key] = "\n".join(current_lines).strip() if current_lines else ""
    return data


def create_agent(api_key=None, base_url="https://api.deepseek.com/v1", db_path=None, strategy_mode=False, confirm_enabled=True, profile: dict = None):
    """创建预配置的 Agent 实例

    Args:
        profile: 可选的 Profile 配置 dict（来自 profiles/*.yaml）
                 会覆盖 db_path、system prompt、工具白名单等
    """
    # ── 应用 Profile 配置 ─────────────────────────────────
    prof_tools = None      # 工具白名单（None = 注册全部）
    prof_overrides = {}    # 风险覆盖

    if profile:
        # 覆盖记忆数据库路径
        if profile.get("db_path"):
            db_path = profile["db_path"]
        # 工具白名单
        prof_tools = profile.get("tools", None)
        # 风险覆盖
        prof_overrides = profile.get("risk_overrides", {}) or {}

    agent = Agent(api_key=api_key, base_url=base_url, memory_store=None,
                  strategy_mode=strategy_mode, confirm_enabled=confirm_enabled)

    # 应用 Profile 的 system prompt
    if profile and profile.get("prompt"):
        agent.set_system_prompt(profile["prompt"].strip())

    memory = MemoryStore(db_path, llm=agent.llm) if db_path else MemoryStore(llm=agent.llm)
    agent.memory = memory
    agent.memory_store = memory

    if agent.memory:
        agent._register_memory_tools()

    # ── 工具注册辅助 ─────────────────────────────────────
    def _reg(name, desc, handler, schema, risk="safe"):
        """仅在白名单（若有）中包含该工具时注册"""
        if prof_tools is not None and name not in prof_tools:
            return
        agent.register_tool(name, desc, handler, schema, risk_level=risk)

    # ── 注册工具（受 Profile 白名单控制） ────────────────
    sub_pool = SubAgentPool(
        api_key=api_key, base_url=base_url,
        tools=agent.tools, parent_agent=agent
    )
    _reg("delegate_task",
         "将子任务交给独立的子 Agent 执行，可并行处理多个独立任务。",
         sub_pool.delegate, DELEGATE_TASK_SCHEMA, "safe")

    _reg("save_skill",
         "将当前经验保存为可复用的技能。",
         agent.skill_manager.save, SAVE_SKILL_SCHEMA, "safe")
    _reg("list_skills",
         "列出所有已保存的技能",
         agent.skill_manager.list, LIST_SKILLS_SCHEMA, "safe")

    _reg("shell", "执行 shell 命令（macOS/Linux）", execute_shell, SHELL_TOOL_SCHEMA, "confirm")
    _reg("read_file", "读取文件内容", read_file, READ_FILE_SCHEMA, "safe")
    _reg("write_file", "写入文件（会覆盖）", write_file, WRITE_FILE_SCHEMA, "confirm")
    _reg("list_files", "列出目录内容", list_files, LIST_FILES_SCHEMA, "safe")
    _reg("docx_to_pdf", "将 Word 文档 (.docx) 转换为 PDF", docx_to_pdf, DOCX_TO_PDF_SCHEMA, "safe")
    _reg("pdf_to_docx", "将 PDF 转换为 Word 文档 (.docx)", pdf_to_docx, PDF_TO_DOCX_SCHEMA, "safe")

    _reg("self_find",
         "【自开发】在 Spider 自己的源码中语义搜索代码。",
         self_find, SELF_FIND_SCHEMA, "safe")
    _reg("web_search",
         "搜索网络，返回相关网页标题和摘要。需要联网查资料时使用。",
         web_search, WEB_SEARCH_SCHEMA, "safe")
    _reg("web_fetch",
         "抓取指定 URL 的网页内容，提取可读文本。需要阅读具体网页时使用。",
         web_fetch, WEB_FETCH_SCHEMA, "safe")

    _reg("self_map",
         "【自开发】查看 Spider 自己的项目结构。",
         self_map, SELF_MAP_SCHEMA, "safe")
    _reg("self_validate",
         "【自开发】验证 Python 文件的语法正确性。",
         self_validate, SELF_VALIDATE_SCHEMA, "safe")
    _reg("self_review",
         "【自开发】审查当前的 git 代码变更。",
         self_review, SELF_REVIEW_SCHEMA, "safe")
    _reg("self_edit",
         "【自开发】安全地修改代码文件。",
         self_edit, SELF_EDIT_SCHEMA, "confirm")
    _reg("self_commit",
         "【自开发】自动提交代码变更到 git。",
         self_commit, SELF_COMMIT_SCHEMA, "confirm")

    # 应用 Profile 的风险覆盖
    for tool_name, risk in prof_overrides.items():
        try:
            agent.tools.set_risk_override(tool_name, risk)
        except Exception:
            pass

    # MCP 服务器（从 mcp_servers.json 加载）
    mcp_config = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_servers.json")
    if os.path.exists(mcp_config):
        agent.mcp_manager = MCPManager(config_path=mcp_config)

    return agent


async def run_task(task: str, api_key=None, base_url=None, db_path=None, strategy_mode=False, confirm_enabled=True, profile=None, profile_name=None):
    """执行单次任务"""
    try:
        agent = create_agent(api_key, base_url, db_path, strategy_mode=strategy_mode, confirm_enabled=confirm_enabled, profile=profile)
        await agent.run(task, cli=cli)
    except AuthError as e:
        print(f"\n{e}")


async def interactive_mode(api_key=None, base_url=None, db_path=None, strategy_mode=False, confirm_enabled=True, profile=None, profile_name=None):
    """交互式模式 — 支持命令历史、Escape 取消、状态显示"""
    agent = create_agent(api_key, base_url, db_path, strategy_mode=strategy_mode, confirm_enabled=confirm_enabled, profile=profile)

    # 预加载 MCP，获取连接信息
    mcp_info = "无"
    if agent.mcp_manager:
        cli.info("🔌 正在连接 MCP 服务器...")
        try:
            await agent._load_mcp()
            mcp_info = agent.mcp_manager.summary()
        except Exception:
            mcp_info = "加载失败"

    # 显示欢迎信息
    cli.welcome(mcp_info=mcp_info)

    if agent.strategy_mode:
        cli.muted("🧠 战略推理模式 (StraTA)")

    while True:
        task = cli.input_prompt()
        if not task:
            continue
        if task in ("/quit", "quit", "exit", "退出"):
            cli.exit_message()
            break
        if task == "/tools":
            cli.display_response("**可用工具：**\n" + format_tools(agent))
            continue
        if task == "/skills":
            cli.display_response(agent.skill_manager.list())
            continue
        if task in ("/help", "/h"):
            cli.display_response(
                "**可用命令：**\n\n"
                "| 命令 | 说明 |\n"
                "|------|------|\n"
                "| `/tools` | 查看所有可用工具 |\n"
                "| `/skills` | 查看已保存的技能 |\n"
                "| `/help` | 显示此帮助 |\n"
                "| `quit` | 退出 |\n"
                "| `⎋ Esc` | 取消当前任务 |"
            )
            continue

        try:
            cli.watch_abort()

            async def run_with_abort():
                async def check_abort():
                    while not cli.abort_pressed():
                        await asyncio.sleep(0.1)

                run_task = asyncio.create_task(agent.run(task, cli=cli))
                check_task = asyncio.create_task(check_abort())
                done, pending = await asyncio.wait(
                    [run_task, check_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cli.abort_pressed():
                    run_task.cancel()
                    for t in pending:
                        t.cancel()
                    return "CANCELLED"
                check_task.cancel()
                return await run_task

            # 执行
            result = await run_with_abort()
            if result == "CANCELLED":
                cli.muted("⎋ 已取消")
            else:
                # 显示统计
                elapsed = agent._elapsed()
                cli.display_stats(agent._turn, elapsed)

        except AuthError as e:
            print(f"\n{e}")
        except asyncio.CancelledError:
            cli.muted("⎋ 已取消")
        finally:
            cli.stop_abort()
            cli.drain_stdin()


def format_tools(agent) -> str:
    """格式化工具列表为 markdown 表格"""
    from core.tool_registry import ToolRegistry
    schemas = agent.tools.schemas
    lines = ["| 工具 | 说明 | 类型 |", "|------|------|------|"]
    for s in schemas:
        fn = s["function"]
        name = fn["name"]
        is_mcp = name.startswith("mcp_")
        ttype = "🔌 MCP" if is_mcp else "🛠️  内置"
        desc = fn.get("description", "")[:60]
        lines.append(f"| `{name}` | {desc} | {ttype} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Spider Agent")
    parser.add_argument("task", nargs="*", help="要执行的任务")
    parser.add_argument("-i", "--interactive", action="store_true", help="交互式模式")
    parser.add_argument("--web", action="store_true", help="启动 Web UI")
    parser.add_argument("--host", default="127.0.0.1", help="Web UI 监听地址 (默认 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8888, help="Web UI 端口 (默认 8888)")
    parser.add_argument("--api-key", help="DeepSeek API Key (默认从 DEEPSEEK_API_KEY 环境变量读取)")
    parser.add_argument("--base-url", default="https://api.deepseek.com/v1", help="API base URL")
    parser.add_argument("--db-path", default=None,
                        help="SQLite 数据库路径 (默认 <项目根>/spider_memory.db)")
    parser.add_argument("--strategy", action="store_true",
                        help="启用 StraTA 战略推理模式")
    parser.add_argument("-y", "--no-confirm", action="store_true",
                        help="跳过所有操作确认（谨慎使用）")
    parser.add_argument("--profile", default=None,
                        help="角色配置名 (profiles/{name}.yaml)，如 finance、coding")

    args = parser.parse_args()

    confirm_enabled = not args.no_confirm

    # 加载 Profile（如果有）
    profile = None
    profile_name = None
    if args.profile:
        profile_name = args.profile
        profile = load_profile(args.profile)
        if profile is None:
            sys.exit(1)

    if args.api_key:
        os.environ["DEEPSEEK_API_KEY"] = args.api_key
    if args.base_url:
        os.environ["DEEPSEEK_BASE_URL"] = args.base_url

    # 显示启动信息
    cli.blank()
    if profile_name:
        display_name = profile.get("display", profile_name) if profile else profile_name
        cli.muted(f"👤 Profile: {display_name}")
    if args.strategy:
        cli.muted("🧠 战略推理模式已启用")
    if args.no_confirm:
        cli.muted("⚡ 确认模式已关闭（所有操作自动放行）")
    cli.blank()

    if args.web:
        try:
            import uvicorn
        except ImportError:
            print("❌ 需要安装 Web 依赖: pip install fastapi uvicorn")
            sys.exit(1)

        from web.app import app
        cli.muted(f"Web UI  →  http://{args.host}:{args.port}")
        cli.blank()
        # 传递配置给 web app
        app.state.strategy_mode = args.strategy
        app.state.confirm_enabled = confirm_enabled
        app.state.profile = profile
        app.state.profile_name = profile_name
        uvicorn.run(app, host=args.host, port=args.port)
        return

    task = " ".join(args.task) if args.task else ""

    if args.interactive or (not task):
        asyncio.run(interactive_mode(args.api_key, args.base_url, args.db_path,
                                      strategy_mode=args.strategy, confirm_enabled=confirm_enabled,
                                      profile=profile, profile_name=profile_name))
    else:
        asyncio.run(run_task(task, args.api_key, args.base_url, args.db_path,
                              strategy_mode=args.strategy, confirm_enabled=confirm_enabled,
                              profile=profile, profile_name=profile_name))


if __name__ == "__main__":
    main()
