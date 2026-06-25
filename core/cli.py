"""
Spider CLI 终端渲染 — Claude Code 风格极简界面
支持 Escape 取消、命令历史、状态显示、等待动画
"""

import atexit
import os
import shutil
import sys
import threading
import select
import time

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.text import Text
    from rich.panel import Panel
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


# ── 调色板 ──────────────────────────────────

class C:
    """颜色常量"""
    PROMPT = "bold #ffb86c"
    TOOL_ICON = "yellow"
    TOOL_NAME = "bold yellow"
    TOOL_ARGS = "dim"
    TOOL_RESULT = "dim"
    SUCCESS = "bold green"
    ERROR = "bold red"
    MUTED = "dim"
    RESPONSE = ""  # 白色
    ACCENT = "cyan"
    WARN = "yellow"
    SPINNER = "bold cyan"
    STATS = "dim #888888"


# ── 历史文件路径 ────────────────────────────

HISTORY_FILE = os.path.expanduser("~/.spider_history")


# ── Escape 监听 ─────────────────────────────

class EscWatcher:
    """后台监听 Escape 键，用于中断任务"""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._old_tty = None
        self._fd = None
        self.pressed = False
        self._stopped = True

    def start(self):
        """开始监听 Escape（设置 cbreak + 启动线程）"""
        if not self._stopped:
            return
        if not sys.stdin.isatty():
            return

        import termios, tty
        self._fd = sys.stdin.fileno()
        self._old_tty = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)

        self._stopped = False
        self.pressed = False

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """停止监听，恢复终端设置"""
        self._stopped = True
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None
        if self._old_tty is not None and self._fd is not None:
            import termios
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_tty)
            except Exception:
                pass
            self._old_tty = None

    def _run(self):
        """线程：轮询 stdin，检测 Escape"""
        while not self._stopped:
            try:
                r, _, _ = select.select([sys.stdin], [], [], 0.2)
                if r:
                    ch = sys.stdin.read(1)
                    if ch == '\x1b':
                        self.pressed = True
                        break
            except (ValueError, OSError):
                break


# ── 等待动画 ────────────────────────────────

class Spinner:
    """简单的等待动画"""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, text="思考中", stream=None):
        self._text = text
        self._running = False
        self._thread: threading.Thread | None = None
        self._stream = stream

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        i = 0
        while self._running:
            frame = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write(f"\r  {frame} {self._text}...")
            sys.stdout.flush()
            time.sleep(0.1)
            i += 1
        # 清除 spinner 行
        sys.stdout.write("\r" + " " * (len(self._text) + 6) + "\r")
        sys.stdout.flush()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)


# ── 主 CLI 类 ───────────────────────────────

class SpiderCLI:
    """极简 CLI 渲染器"""

    def __init__(self):
        self.console = Console(highlight=False) if HAS_RICH else None
        self._width = shutil.get_terminal_size((80, 24)).columns
        self._esc = EscWatcher()
        self._spinner = None
        # 会话统计
        self.turn_count = 0
        self.tool_count = 0
        self.session_start = None

        # 初始化 readline 历史
        self._init_history()

    def _init_history(self):
        """启用 readline 上下箭头历史"""
        try:
            import readline
            try:
                readline.read_history_file(HISTORY_FILE)
            except (FileNotFoundError, OSError):
                pass
            readline.set_history_length(200)
            atexit.register(lambda: self._save_history())
        except ImportError:
            pass  # 不支持 readline 的平台（如 Windows）

    @staticmethod
    def _save_history():
        try:
            import readline
            readline.write_history_file(HISTORY_FILE)
        except Exception:
            pass

    # ── 欢迎信息 ──────────────────────────────

    def welcome(self, mcp_info: str = ""):
        """显示启动欢迎和命令提示"""
        if not self.console or not HAS_RICH:
            print("🕷️ Spider 轻量级 Agent 系统\n")
            return

        lines = [
            "🕷️  Spider 轻量级 Agent 系统",
            "",
        ]
        if mcp_info and mcp_info != "无":
            lines.append(f"   🔌 MCP: {mcp_info}")
        lines.append("")
        lines.append("   /tools  查看可用工具    /help  帮助")
        lines.append("   /skills 查看技能列表    quit   退出")
        lines.append("   ⎋ Escape 取消当前任务")
        lines.append("")

        panel = Panel(
            Text("\n".join(lines[1:])),
            title="[bold #ffb86c]🕷️  Spider[/]",
            subtitle="[dim]轻量级 Agent 系统[/]",
            box=box.ROUNDED,
            border_style="dim",
        )
        self.console.print(panel)

    # ── Escape 取消 ──────────────────────────

    def watch_abort(self):
        self._esc.start()

    def abort_pressed(self) -> bool:
        return self._esc.pressed

    def stop_abort(self):
        self._esc.stop()

    def drain_stdin(self):
        """排出残留的 stdin 字符，避免影响下一次 input()"""
        if not sys.stdin.isatty():
            return
        import termios, tty
        try:
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                while select.select([sys.stdin], [], [], 0)[0]:
                    sys.stdin.read(1)
            except Exception:
                pass
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            pass

    # ── 等待动画 ─────────────────────────────

    def start_spinner(self, text="思考中"):
        """开始显示等待动画"""
        self._spinner = Spinner(text)
        self._spinner.start()

    def stop_spinner(self):
        """停止等待动画"""
        if self._spinner:
            self._spinner.stop()
            self._spinner = None

    # ── 用户输入 ─────────────────────────────

    def input_prompt(self) -> str:
        """显示带颜色的 '> ' 提示符，支持历史"""
        try:
            if self.console and HAS_RICH:
                self.console.print("> ", style=C.PROMPT, end="")
            else:
                print("> ", end="", flush=True)

            text = input()

            # 输入完成后，把整行重绘为琥珀金
            if text and self.console and HAS_RICH:
                self.console.print(f"\033[1A\033[K> {text}", style=C.PROMPT)

            return text.strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    # ── 助手回复 ─────────────────────────────

    def display_response(self, text: str):
        """显示助手回复（Markdown 渲染）"""
        if not text:
            return
        if self.console and HAS_RICH:
            try:
                md = Markdown(text, code_theme="monokai", style=C.RESPONSE)
                self.console.print(md)
            except Exception:
                self.console.print(text, style=C.RESPONSE)
        else:
            print(text)

    def stream_response(self, chunk: str):
        """流式输出内容块"""
        if self.console and HAS_RICH:
            self.console.print(chunk, style=C.RESPONSE, end="")
        else:
            print(chunk, end="", flush=True)

    def stream_done(self):
        """流式输出结束，换行"""
        print()

    # ── 工具调用 ─────────────────────────────

    def display_tool_call(self, name: str, args: dict):
        """显示工具调用 — 单行"""
        # MCP 工具特殊图标
        is_mcp = name.startswith("mcp_")
        icon = "🔌" if is_mcp else "⚡"

        args_str = ", ".join(f"{k}={v}" for k, v in args.items())
        if len(args_str) > 80:
            args_str = args_str[:77] + "..."
        if self.console and HAS_RICH:
            t = Text()
            t.append("  ", style=C.MUTED)
            t.append(f"{icon} ", style=C.TOOL_ICON)
            # MCP 工具名缩短显示
            display_name = name
            if is_mcp:
                parts = name.split("_", 2)
                if len(parts) >= 3:
                    display_name = f"{parts[1]}:{parts[2]}"
            t.append(display_name, style=C.TOOL_NAME)
            t.append(f"({args_str})", style=C.TOOL_ARGS)
            self.console.print(t)
        else:
            print(f"  {icon} {name}({args_str})")

    def display_tool_result(self, result: str):
        """工具结果 — 单行预览，大结果折叠"""
        preview = result.replace("\n", " ").strip()
        if not preview:
            return

        if len(preview) > 120:
            preview = preview[:117] + "..."

        # 检查是否有图片等大负载
        if len(result) > 500:
            size_kb = round(len(result) / 1024, 1)
            preview = f"[{size_kb}KB 数据]"

        if self.console and HAS_RICH:
            t = Text()
            t.append("  └─ ", style=C.MUTED)
            t.append(preview, style=C.TOOL_RESULT)
            self.console.print(t)
        else:
            print(f"  └─ {preview}")

    # ── 技能步骤 ─────────────────────────────

    def display_step(self, step_name: str, tool_name: str, params: dict):
        """显示技能步骤开始执行"""
        args_str = ", ".join(f"{k}={v}" for k, v in params.items())
        if self.console and HAS_RICH:
            t = Text()
            t.append("  ", style=C.MUTED)
            t.append("📋 ", style=C.ACCENT)
            t.append(step_name, style=C.TOOL_NAME)
            t.append(f" → {tool_name}({args_str})", style=C.TOOL_ARGS)
            self.console.print(t)
        else:
            print(f"  📋 {step_name} → {tool_name}({args_str})")

    # ── 会话统计 ─────────────────────────────

    def display_stats(self, turns: int, elapsed: str):
        """显示本轮会话统计"""
        if self.console and HAS_RICH:
            t = Text()
            t.append(f"  ── {turns} 轮 · {elapsed}", style=C.STATS)
            self.console.print(t)
        else:
            print(f"  ── {turns} 轮 · {elapsed}")
        print()  # 空行分隔

    # ── 状态消息 ─────────────────────────────

    def info(self, msg: str):
        """显示信息消息"""
        if self.console and HAS_RICH:
            self.console.print(f"  {msg}", style=C.ACCENT)
        else:
            print(f"  {msg}")

    def success(self, msg: str):
        if self.console and HAS_RICH:
            self.console.print(f"  {msg}", style=C.SUCCESS)
        else:
            print(f"  {msg}")

    def error(self, msg: str):
        if self.console and HAS_RICH:
            self.console.print(f"  {msg}", style=C.ERROR)
        else:
            print(f"  {msg}")

    def muted(self, msg: str):
        if self.console and HAS_RICH:
            self.console.print(f"  {msg}", style=C.MUTED)
        else:
            print(f"  {msg}")

    # ── 分隔线 ───────────────────────────────

    def blank(self):
        """输出空行"""
        print()

    # ── 退出 ─────────────────────────────────

    def exit_message(self):
        if self.console and HAS_RICH:
            self.console.print("\n  Goodbye! 👋\n", style=C.SUCCESS)
        else:
            print("\n  Goodbye!\n")
