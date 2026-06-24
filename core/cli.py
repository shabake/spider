"""
Spider CLI 终端渲染 — Claude Code 风格极简界面
支持 Escape 取消当前任务
"""

import shutil
import sys
import threading
import select

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.text import Text
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
            return  # 已在运行
        if not sys.stdin.isatty():
            return

        import termios, tty
        self._fd = sys.stdin.fileno()
        self._old_tty = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)

        self._stopped = False
        self.pressed = False  # 供外部检查

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


class SpiderCLI:
    """极简 CLI 渲染器 — 仿 Claude Code 风格"""

    def __init__(self):
        self.console = Console(highlight=False) if HAS_RICH else None
        self._width = shutil.get_terminal_size((80, 24)).columns
        self._esc = EscWatcher()

    # ── Escape 取消 ──────────────────────────────

    def watch_abort(self):
        """开始监听 Escape 取消"""
        self._esc.start()

    def abort_pressed(self) -> bool:
        """Escape 是否被按下"""
        return self._esc.pressed

    def stop_abort(self):
        """停止监听，恢复终端"""
        self._esc.stop()

    def drain_stdin(self):
        """排出残留的 stdin 字符，避免影响下一次 input()"""
        import termios, tty
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

    # ── 用户输入 ─────────────────────────────────

    def input_prompt(self) -> str:
        """显示带颜色的 '> ' 提示符"""
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

    # ── 助手回复 ─────────────────────────────────

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

    # ── 工具调用 ─────────────────────────────────

    def display_tool_call(self, name: str, args: dict):
        """显示工具调用 — 单行"""
        args_str = ", ".join(f"{k}={v}" for k, v in args.items())
        if len(args_str) > 80:
            args_str = args_str[:77] + "..."
        if self.console and HAS_RICH:
            t = Text()
            t.append("  ", style=C.MUTED)
            t.append("⚡ ", style=C.TOOL_ICON)
            t.append(name, style=C.TOOL_NAME)
            t.append(f"({args_str})", style=C.TOOL_ARGS)
            self.console.print(t)
        else:
            print(f"  ⚡ {name}({args_str})")

    def display_tool_result(self, result: str):
        """工具结果 — 单行预览"""
        preview = result.replace("\n", " ").strip()[:120]
        if not preview:
            return
        if self.console and HAS_RICH:
            t = Text()
            t.append("  └─ ", style=C.MUTED)
            t.append(preview, style=C.TOOL_RESULT)
            self.console.print(t)
        else:
            print(f"  └─ {preview}")

    # ── 状态消息 ─────────────────────────────────

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

    # ── 退出 ────────────────────────────────────

    def exit_message(self):
        if self.console and HAS_RICH:
            self.console.print("\n  Goodbye!\n", style=C.SUCCESS)
        else:
            print("\n  Goodbye!\n")
