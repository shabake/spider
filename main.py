#!/usr/bin/env python3
"""
Spider — 轻量级 Agent 系统 (仿 Hermes 设计模式)

用法:
    python main.py "你的任务"
    python main.py --interactive
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

# 🕷️ 蜘蛛名言集
SPIDER_QUOTES = [
    "蜘蛛虽小，五脏俱全",
    "网织好了，等风来",
    "行动派不需要翅膀",
    "代码如丝，连接万物",
    "一步一个脚印，八条腿也是",
    "沉默的织网者",
    "在最暗的角落也能闪亮",
    "不结网的蜘蛛不是好蜘蛛",
]


def create_agent(api_key=None, base_url="https://api.deepseek.com/v1", db_path=None):
    """创建预配置的 Agent 实例"""
    # 先创建 Agent（内部会初始化 LLM）
    agent = Agent(api_key=api_key, base_url=base_url, memory_store=None)

    # 然后用 Agent 的 LLM 初始化 MemoryStore（实现向量语义搜索）
    memory = MemoryStore(db_path, llm=agent.llm) if db_path else MemoryStore(llm=agent.llm)
    agent.memory = memory
    agent.memory_store = memory

    # 注册记忆工具（因为之前 memory 是 None，现在补上）
    if agent.memory:
        agent._register_memory_tools()

    # 子代理工具
    sub_pool = SubAgentPool(
        api_key=api_key, base_url=base_url,
        tools=agent.tools, parent_agent=agent
    )
    agent.register_tool(
        "delegate_task",
        "将子任务交给独立的子 Agent 执行，可并行处理多个独立任务。"
        "适合: 同时查多个信息、独立子任务、需要隔离上下文的任务",
        sub_pool.delegate, DELEGATE_TASK_SCHEMA
    )

    # 技能工具
    agent.register_tool(
        "save_skill",
        "将当前经验保存为可复用的技能。当你发现一个有效的任务解决方法时调用此工具。",
        agent.skill_manager.save, SAVE_SKILL_SCHEMA
    )
    agent.register_tool(
        "list_skills",
        "列出所有已保存的技能",
        agent.skill_manager.list, LIST_SKILLS_SCHEMA
    )

    # 注册内置工具
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

    # ── Self-Dev 工具 ──────────────────────────────────────
    agent.register_tool(
        "self_find",
        '【自开发】在 Spider 自己的源码中语义搜索代码。'
        '传入自然语言描述，找到对应的函数、类、变量位置。'
        '适合: 搜索 "recall 函数在哪"、"记忆系统的搜索逻辑"',
        self_find, SELF_FIND_SCHEMA
    )
    agent.register_tool(
        "self_map",
        '【自开发】查看 Spider 自己的项目结构。'
        '了解有哪些模块、每个文件负责什么、代码量统计。'
        '开发新功能前先看这个，避免改错文件。',
        self_map, SELF_MAP_SCHEMA
    )
    agent.register_tool(
        "self_validate",
        '【自开发】验证 Python 文件的语法正确性。'
        '修改代码后使用，检查是否有语法错误。',
        self_validate, SELF_VALIDATE_SCHEMA
    )
    agent.register_tool(
        "self_review",
        '【自开发】审查当前的 git 代码变更。'
        '修改代码后、提交前使用，看看改了哪些文件。',
        self_review, SELF_REVIEW_SCHEMA
    )
    agent.register_tool(
        "self_edit",
        '【自开发】安全地修改代码文件。'
        '自动备份 → 替换 → 语法验证 → 失败回滚。'
        '修改代码时使用，比直接 write_file 更安全。',
        self_edit, SELF_EDIT_SCHEMA
    )
    agent.register_tool(
        "self_commit",
        '【自开发】自动提交代码变更到 git。'
        '自动 add 变更文件 → commit。'
        '功能验证通过后使用。',
        self_commit, SELF_COMMIT_SCHEMA
    )

    return agent


async def run_task(task: str, api_key=None, base_url=None, db_path=None):
    """执行单次任务"""
    try:
        agent = create_agent(api_key, base_url, db_path)
        await agent.run(task)
    except AuthError as e:
        print(f"\n{e}")


async def interactive_mode(api_key=None, base_url=None, db_path=None):
    """交互式模式"""
    agent = create_agent(api_key, base_url, db_path)
    print("🕷️ Spider Agent — 输入 /help 查看命令, /quit 退出")
    print("=" * 50)

    while True:
        try:
            task = input("\n🙋 ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        if not task:
            continue
        if task == "/quit":
            break
        if task == "/help":
            print("  /quit  — 退出")
            print("  /tools — 查看可用工具")
            print("  其他   — 作为任务执行")
            continue
        if task == "/tools":
            print("可用工具:", ", ".join(agent.tools.names))
            continue

        try:
            await agent.run(task)
        except AuthError as e:
            print(f"\n{e}")


def main():
    print()
    print("🕷️ ", random.choice(SPIDER_QUOTES))
    print()
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

    # 设置环境变量
    if args.api_key:
        os.environ["DEEPSEEK_API_KEY"] = args.api_key
    if args.base_url:
        os.environ["DEEPSEEK_BASE_URL"] = args.base_url

    if args.web:
        # 启动 Web UI
        try:
            import uvicorn
        except ImportError:
            print("❌ 需要安装 Web 依赖: pip install fastapi uvicorn")
            sys.exit(1)

        from web.app import app
        print(f"🕷️ Spider Web UI 启动中...")
        print(f"   地址: http://{args.host}:{args.port}")
        print(f"   按 Ctrl+C 停止")
        uvicorn.run(app, host=args.host, port=args.port)
        return

    task = " ".join(args.task) if args.task else ""

    if args.interactive or (not task):
        asyncio.run(interactive_mode(args.api_key, args.base_url, args.db_path))
    else:
        asyncio.run(run_task(task, args.api_key, args.base_url, args.db_path))


if __name__ == "__main__":
    main()
