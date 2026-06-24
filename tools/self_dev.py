"""
Spider 自我开发工具集

让 Spider 能够理解、修改、验证自己的代码。
这是"蜘蛛自己开发自己"的基础设施。
"""

import ast
import importlib.util
import json
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 项目结构认知 ────────────────────────────

SELF_MAP_SCHEMA = {
    "type": "object",
    "properties": {
        "detail": {
            "type": "string",
            "description": "详细程度: 'brief' 只看模块, 'full' 包含子目录",
            "default": "brief",
        },
    },
}


async def self_map(detail: str = "brief") -> str:
    """
    让 Spider 了解自己的项目结构

    Returns 项目模块概览，包含每个文件的功能说明
    """
    # 核心模块说明
    modules = {
        "core/agent.py": "Agent 核心循环 (ReAct)，负责任务调度和工具调用",
        "core/llm.py": "LLM 调用封装，支持 streaming、tool calls、embedding",
        "core/tool_registry.py": "工具注册中心，管理所有可用工具",
        "core/sub_agent.py": "子代理系统，支持任务委托和并行执行",
        "core/skill_manager.py": "技能系统，管理和匹配 YAML 技能文件",
        "core/memory.py": "持久化记忆系统，SQLite + FTS5 + 向量语义搜索",
        "tools/shell.py": "Shell 命令执行工具",
        "tools/read_write.py": "文件读写操作工具",
        "tools/convert.py": "文档格式转换 (docx/PDF)",
        "tools/self_dev.py": "自我开发工具集 (就是你正在用的)",
        "web/app.py": "FastAPI Web 后端，SSE 实时推送",
        "web/templates/index.html": "Web UI 聊天界面 HTML",
        "web/static/css/style.css": "Web UI 深色主题样式",
        "web/static/js/chat.js": "Web UI 前端交互逻辑",
        "main.py": "CLI 入口，支持 单次/交互/Web 三种模式",
    }

    lines = ["🕷️ Spider 项目全景:\n"]

    # 显示目录树
    lines.append("📁 项目结构:")
    for path, desc in modules.items():
        indent = "  " * (path.count("/"))
        lines.append(f"  {indent}{path}  ← {desc}")

    # 统计
    lines.append(f"\n📊 概况:")
    total_lines = 0
    for path in modules:
        full_path = os.path.join(PROJECT_ROOT, path)
        if os.path.exists(full_path):
            try:
                with open(full_path) as f:
                    count = len(f.readlines())
                    total_lines += count
                    lines.append(f"  • {path}: {count} 行")
            except Exception:
                pass
    lines.append(f"\n  📦 总计: {total_lines} 行 Python/CSS/JS 代码")

    return "\n".join(lines)


# ── 语义代码搜索 ────────────────────────────

SELF_FIND_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "搜索关键词，如 'recall'、'MemoryStore'、'cosine_similarity'",
        },
        "file_filter": {
            "type": "string",
            "description": "限定文件（可选），如 'core/memory.py' 或 '*memory*'",
            "default": "",
        },
        "context_lines": {
            "type": "integer",
            "description": "匹配行上下各显示多少行上下文",
            "default": 3,
        },
    },
    "required": ["query"],
}


async def self_find(query: str, file_filter: str = "", context_lines: int = 3) -> str:
    """
    在 Spider 自己的源码中搜索代码

    - 使用语义理解：能找到 "存记忆" 对应 save_memory 函数
    - 支持文件过滤和上下文显示
    """
    if not query.strip():
        return "❌ 请输入搜索关键词"

    src_dirs = [
        os.path.join(PROJECT_ROOT, "core"),
        os.path.join(PROJECT_ROOT, "tools"),
        os.path.join(PROJECT_ROOT, "web"),
    ]

    matches = []

    for src_dir in src_dirs:
        if not os.path.exists(src_dir):
            continue
        for root, dirs, files in os.walk(src_dir):
            # 跳过 __pycache__
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(root, fname)
                rel_path = os.path.relpath(fpath, PROJECT_ROOT)

                # 文件过滤
                if file_filter:
                    if file_filter.startswith("*"):
                        if file_filter[1:] not in fname:
                            continue
                    elif file_filter not in rel_path:
                        continue

                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    continue

                # 搜索（大小写不敏感）
                q = query.lower()
                lines = content.split("\n")
                for i, line in enumerate(lines):
                    if q in line.lower():
                        start = max(0, i - context_lines)
                        end = min(len(lines), i + context_lines + 1)
                        snippet = lines[start:end]
                        line_num = i + 1

                        matches.append({
                            "file": rel_path,
                            "line": line_num,
                            "snippet": snippet,
                            "mid_idx": i - start,
                        })

    if not matches:
        return f"🔍 未找到包含 '{query}' 的代码\n  试试换个关键词，或者用 'self_map' 查看项目结构"

    # 分组按文件
    by_file = {}
    for m in matches:
        by_file.setdefault(m["file"], []).append(m)

    result = [f"🔍 找到 {len(matches)} 处匹配 '{query}':\n"]
    for fpath, file_matches in by_file.items():
        result.append(f"\n📄 {fpath}:")
        for m in file_matches[:5]:  # 每个文件最多 5 处
            result.append(f"  ── 第 {m['line']} 行 ──")
            for j, snippet_line in enumerate(m["snippet"]):
                marker = "→" if j == m["mid_idx"] else " "
                result.append(f"  {marker} {snippet_line}")
            result.append("")

    if sum(len(v) for v in by_file.values()) > 20:
        result.append(f"  ... 还有更多，用 file_filter 缩小范围")

    return "\n".join(result)


# ── 语法验证 ────────────────────────────────

SELF_VALIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "filepath": {
            "type": "string",
            "description": "要验证的文件路径（相对于项目根目录），如 'core/memory.py'",
        },
    },
    "required": ["filepath"],
}


async def self_validate(filepath: str) -> str:
    """
    验证 Python 文件的语法正确性

    在修改代码后调用，确保没有语法错误
    """
    full_path = os.path.join(PROJECT_ROOT, filepath)
    if not os.path.exists(full_path):
        return f"❌ 文件不存在: {filepath}"

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        return f"❌ 无法读取文件: {e}"

    # AST 语法检查
    try:
        ast.parse(source, filename=filepath)
    except SyntaxError as e:
        return f"❌ 语法错误: {e.msg}\n  文件: {filepath}:{e.lineno}:{e.offset}\n  {e.text}"

    # import 完整性检查（尝试编译）
    try:
        compile(source, filepath, "exec")
    except Exception as e:
        return f"⚠️  语法通过，但编译警告: {e}"

    # 行数统计
    lines = source.split("\n")
    code_lines = [l for l in lines if l.strip() and not l.strip().startswith("#")]
    return (
        f"✅ 语法检查通过\n"
        f"  文件: {filepath}\n"
        f"  总行数: {len(lines)}\n"
        f"  代码行: {len(code_lines)}\n"
        f"  注释/空行: {len(lines) - len(code_lines)}"
    )


# ── Git 变更审查 ────────────────────────────

SELF_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "staged": {
            "type": "boolean",
            "description": "是否只看已暂存(staged)的变更，默认 false 看全部未提交变更",
            "default": False,
        },
    },
}


async def self_review(staged: bool = False) -> str:
    """
    审查当前的代码变更（git diff）

    在修改代码之后、提交之前调用，确认改了什么
    """
    try:
        # 检查是否在 git 仓库中
        subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "⚠️  不是 git 仓库，无法审查变更"

    # git diff
    cmd = ["git", "diff"]
    if staged:
        cmd.append("--cached")
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10
        )
    except subprocess.TimeoutExpired:
        return "⏱️  git diff 超时"

    diff = result.stdout
    if not diff.strip():
        return "📭 没有未提交的变更"

    # 解析 diff 统计
    files_changed = set()
    added = 0
    removed = 0
    for line in diff.split("\n"):
        if line.startswith("+++ b/"):
            files_changed.add(line[6:])
        elif line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1

    # 截断太长
    if len(diff) > 3000:
        diff = diff[:3000] + "\n... (截断，完整变更请用 git diff)"

    return (
        f"📋 代码变更审查\n"
        f"{'='*40}\n"
        f"  变更文件: {len(files_changed)}\n"
        f"  增加行: {added}\n"
        f"  删除行: {removed}\n\n"
        f"📄 变更文件:\n"
        + "\n".join(f"  • {f}" for f in sorted(files_changed))
        + f"\n\n{diff}"
    )


# ── 执行 Python 代码（沙箱测试）────────────

SELF_RUN_SCHEMA = {
    "type": "object",
    "properties": {
        "filepath": {
            "type": "string",
            "description": "要运行的 Python 文件路径（相对于项目根目录）",
        },
        "args": {
            "type": "string",
            "description": "命令行参数",
            "default": "",
        },
        "timeout": {
            "type": "integer",
            "description": "超时秒数",
            "default": 15,
        },
    },
    "required": ["filepath"],
}


async def self_run(filepath: str, args: str = "", timeout: int = 15) -> str:
    """
    运行一个 Python 文件并获取输出

    用于快速测试修改后的代码能否正常运行
    """
    full_path = os.path.join(PROJECT_ROOT, filepath)
    if not os.path.exists(full_path):
        return f"❌ 文件不存在: {filepath}"

    cmd = [sys.executable, full_path]
    if args:
        cmd.extend(args.split())

    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout
        )
        output = []
        if result.stdout:
            output.append(f"📤 标准输出:\n{result.stdout[:2000]}")
        if result.stderr:
            output.append(f"📥 标准错误:\n{result.stderr[:2000]}")
        if result.returncode != 0:
            output.insert(0, f"❌ 退出码: {result.returncode}")
        else:
            output.insert(0, f"✅ 执行成功 (退出码: 0)")
        return "\n".join(output)
    except subprocess.TimeoutExpired:
        return f"⏱️ 执行超时 ({timeout}s)"
    except Exception as e:
        return f"❌ 执行失败: {e}"


# ── 安全编辑 ────────────────────────────────────────

SELF_EDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "filepath": {
            "type": "string",
            "description": "要修改的文件路径（相对于项目根目录），如 'core/memory.py'",
        },
        "old_string": {
            "type": "string",
            "description": "要被替换的旧文本（精确匹配）",
        },
        "new_string": {
            "type": "string",
            "description": "新文本",
        },
    },
    "required": ["filepath", "old_string", "new_string"],
}


async def self_edit(filepath: str, old_string: str, new_string: str) -> str:
    """
    安全地修改代码文件

    - 自动创建 .bak 备份
    - 修改后自动验证语法
    - 验证失败自动回滚
    - 返回 diff 摘要
    """
    full_path = os.path.join(PROJECT_ROOT, filepath)
    if not os.path.exists(full_path):
        return f"❌ 文件不存在: {filepath}"

    if not old_string:
        return "❌ old_string 不能为空"

    # 读原文件
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        return f"❌ 读取失败: {e}"

    # 检查旧文本存在
    if old_string not in source:
        # 尝试模糊提示
        lines = source.split("\n")
        hint_words = old_string.split("\n")[0].strip()[:20]
        found_hint = ""
        for i, line in enumerate(lines):
            if hint_words in line:
                found_hint = f"\n  附近行 {i+1}: {line.strip()[:80]}"
                break
        return (
            f"❌ 未找到匹配的 old_string"
            f"{found_hint}"
            f"\n\n提示: old_string 必须精确匹配文件中的内容（包括缩进）"
        )

    # 备份
    bak_path = full_path + ".bak"
    try:
        with open(bak_path, "w", encoding="utf-8") as f:
            f.write(source)
    except Exception as e:
        return f"❌ 备份失败: {e}"

    # 修改
    new_source = source.replace(old_string, new_string, 1)
    if new_source == source:
        return "❌ 替换后内容无变化（old_string 可能未匹配到）"

    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(new_source)
    except Exception as e:
        # 写失败，尝试回滚
        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(source)
        except Exception:
            pass
        return f"❌ 写入失败 (已回滚): {e}"

    # 语法验证
    try:
        ast.parse(new_source, filename=filepath)
    except SyntaxError as e:
        # 语法错误，回滚
        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(source)
        except Exception:
            pass
        try:
            os.remove(bak_path)
        except Exception:
            pass
        return (
            f"❌ 修改导致语法错误，已自动回滚\n"
            f"  文件: {filepath}:{e.lineno}:{e.offset}\n"
            f"  错误: {e.msg}\n"
            f"  原文: {e.text}"
        )

    # 清理备份
    try:
        os.remove(bak_path)
    except Exception:
        pass

    # 生成 diff 摘要
    old_lines = source.split("\n")
    new_lines = new_source.split("\n")
    diff_lines = []
    for i, (ol, nl) in enumerate(zip(old_lines, new_lines)):
        if ol != nl:
            diff_lines.append(f"  -{i+1}: {ol}")
            diff_lines.append(f"  +{i+1}: {nl}")

    # 计算统计
    added = sum(1 for l in new_source.split("\n") if l.strip() and l not in source)
    removed = sum(1 for l in source.split("\n") if l.strip() and l not in new_source)

    return (
        f"✅ 修改成功\n"
        f"  文件: {filepath}\n"
        f"  变更: +{added} / -{removed} 行\n\n"
        f"📋 变更详情:\n" + "\n".join(diff_lines[:30]) +
        ("\n  ... (截断)" if len(diff_lines) > 30 else "")
    )


# ── Git 提交 ────────────────────────────────────────

SELF_COMMIT_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": "提交信息，如 'feat: 添加语义搜索支持'",
        },
        "files": {
            "type": "string",
            "description": "要提交的文件（可选，用空格分隔），默认所有变更",
            "default": "",
        },
    },
    "required": ["message"],
}


async def self_commit(message: str, files: str = "") -> str:
    """
    自动提交代码变更到 git

    - 自动 git add 变更文件
    - git commit 并返回结果
    """
    if not message.strip():
        return "❌ 提交信息不能为空"

    # 检查 git 仓库
    try:
        subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=PROJECT_ROOT, capture_output=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "⚠️  不是 git 仓库，无法提交"

    # 检查是否有变更
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10,
    )
    if not status.stdout.strip():
        return "📭 没有未提交的变更"

    # git add
    if files.strip():
        # 指定文件
        file_list = files.strip().split()
        for f in file_list:
            subprocess.run(
                ["git", "add", f],
                cwd=PROJECT_ROOT, capture_output=True, timeout=10,
            )
        added = file_list
    else:
        # 所有变更
        subprocess.run(
            ["git", "add", "-A"],
            cwd=PROJECT_ROOT, capture_output=True, timeout=10,
        )
        # 解析改了哪些文件
        changed = []
        for line in status.stdout.strip().split("\n"):
            parts = line.strip().split(maxsize=1)
            if len(parts) == 2:
                changed.append(parts[1])
        added = changed

    if not added:
        return "📭 没有文件被暂存"

    # git commit
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10,
    )

    if result.returncode == 0:
        return (
            f"✅ 提交成功\n"
            f"  信息: {message}\n"
            f"  文件: {', '.join(added)}\n"
            f"  {result.stdout.strip()}"
        )
    else:
        return f"❌ 提交失败:\n  {result.stderr.strip()}"
