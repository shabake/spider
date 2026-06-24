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
from core.cli import SpiderCLI
from tools.shell import execute_shell, SHELL_TOOL_SCHEMA
from tools.read_write import read_file, write_file, list_files, READ_FILE_SCHEMA, WRITE_FILE_SCHEMA, LIST_FILES_SCHEMA
from tools.convert import docx_to_pdf, pdf_to_docx, DOCX_TO_PDF_SCHEMA, PDF_TO_DOCX_SCHEMA
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


def create_agent(api_key=None, base_url="https://api.deepseek.com/v1", db_path=None):
    """创建预配置的 Agent 实例"""
    agent = Agent(api_key=api_key, base_url=base_url, memory_store=None)

    memory = MemoryStore(db_path, llm=agent.llm) if db_path else MemoryStore(llm=agent.llm)
    agent.memory = memory
    agent.memory_store = memory

    if agent.memory:
        agent._register_memory_tools()

    sub_pool = SubAgentPool(
        api_key=api_key, base_url=base_url,
        tools=agent.tools, parent_agent=agent
    )
    agent.register_tool(
        "delegate_task",
        "将子任务交给独立的子 Agent 执行，可并行处理多个独立任务。",
        sub_pool.delegate, DELEGATE_TASK_SCHEMA
    )

    agent.register_tool(
        "save_skill",
        "将当前经验保存为可复用的技能。",
        agent.skill_manager.save, SAVE_SKILL_SCHEMA
    )
    agent.register_tool(
        "list_skills",
        "列出所有已保存的技能",
        agent.skill_manager.list, LIST_SKILLS_SCHEMA
    )

    agent.register_tool(
        "shell", "执行 shell 命令（macOS/Linux）", execute_shell, SHELL_TOOL_SCHEMA
    )
    agent.register_tool(
        "read_file", "读取文件内容", read_file, READ_FILE_SCHEMA
    )
    agent.register_tool(
        "write_file", "写入文件（会覆盖）", write_file, WRITE_FILE_SCHEMA
    )
    agent.register_tool(
        "list_files", "列出目录内容", list_files, LIST_FILES_SCHEMA
    )
    agent.register_tool(
        "docx_to_pdf", "将 Word 文档 (.docx) 转换为 PDF", docx_to_pdf, DOCX_TO_PDF_SCHEMA
    )
    agent.register_tool(
        "pdf_to_docx", "将 PDF 转换为 Word 文档 (.docx)", pdf_to_docx, PDF_TO_DOCX_SCHEMA
    )

    agent.register_tool(
        "self_find",
        "【自开发】在 Spider 自己的源码中语义搜索代码。",
        self_find, SELF_FIND_SCHEMA
    )
    agent.register_tool(
        "self_map",
        "【自开发】查看 Spider 自己的项目结构。",
        self_map, SELF_MAP_SCHEMA
    )
    agent.register_tool(
        "self_validate",
        "【自开发】验证 Python 文件的语法正确性。",
        self_validate, SELF_VALIDATE_SCHEMA
    )
    agent.register_tool(
        "self_review",
        "【自开发】审查当前的 git 代码变更。",
        self_review, SELF_REVIEW_SCHEMA
    )
    agent.register_tool(
        "self_edit",
        "【自开发】安全地修改代码文件。",
        self_edit, SELF_EDIT_SCHEMA
    )
    agent.register_tool(
        "self_commit",
        "【自开发】自动提交代码变更到 git。",
        self_commit, SELF_COMMIT_SCHEMA
    )

    return agent


async def run_task(task: str, api_key=None, base_url=None, db_path=None):
    """执行单次任务"""
    try:
        agent = create_agent(api_key, base_url, db_path)
        await agent.run(task, cli=cli)
    except AuthError as e:
        print(f"\n{e}")


async def interactive_mode(api_key=None, base_url=None, db_path=None):
    """交互式模式 — Claude Code 风格，Escape 取消当前任务"""
    agent = create_agent(api_key, base_url, db_path)

    while True:
        task = cli.input_prompt()
        if not task:
            continue
        if task in ("/quit", "quit", "exit", "退出"):
            cli.exit_message()
            break

        try:
            # 启动 Escape 监听，支持取消
            cli.watch_abort()

            # agent.run 期间检测 Escape
            async def run_with_abort():
                async def check_abort():
                    while not cli.abort_pressed():
                        await asyncio.sleep(0.1)
                # 同时跑 agent 和检查
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

            result = await run_with_abort()
            if result == "CANCELLED":
                cli.muted("已取消 (按 Esc)")
        except AuthError as e:
            print(f"\n{e}")
        except asyncio.CancelledError:
            cli.muted("已取消 (按 Esc)")
        finally:
            cli.stop_abort()
            cli.drain_stdin()


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

    args = parser.parse_args()

    if args.api_key:
        os.environ["DEEPSEEK_API_KEY"] = args.api_key
    if args.base_url:
        os.environ["DEEPSEEK_BASE_URL"] = args.base_url

    if args.web:
        try:
            import uvicorn
        except ImportError:
            print("❌ 需要安装 Web 依赖: pip install fastapi uvicorn")
            sys.exit(1)

        from web.app import app
        cli.blank()
        cli.muted(f"Web UI  →  http://{args.host}:{args.port}")
        cli.blank()
        uvicorn.run(app, host=args.host, port=args.port)
        return

    task = " ".join(args.task) if args.task else ""

    if args.interactive or (not task):
        asyncio.run(interactive_mode(args.api_key, args.base_url, args.db_path))
    else:
        asyncio.run(run_task(task, args.api_key, args.base_url, args.db_path))


if __name__ == "__main__":
    main()
