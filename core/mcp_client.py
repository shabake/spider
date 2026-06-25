"""
MCP (Model Context Protocol) 客户端

让 Spider 通过 MCP 协议连接外部工具服务（computer-use、macOS 控制等）。
支持 stdio 传输，自动发现工具并注册到 ToolRegistry。

MCP 协议: https://spec.modelcontextprotocol.io/
"""

import asyncio
import json
import logging
import os

logger = logging.getLogger("spider.mcp")


class MCPError(Exception):
    """MCP 基础异常"""


class MCPConnectionError(MCPError):
    """连接异常"""


class MCPToolCallError(MCPError):
    """工具调用异常"""


class MCPServer:
    """单个 MCP 服务器连接（stdio 传输）"""

    def __init__(self, name: str, command: str, args: list[str] = None):
        self.name = name
        self.command = command
        self.args = args or []
        self._process = None
        self._reader = None
        self._writer = None
        self._req_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._running = False
        self._tool_list: list[dict] = []

    async def start(self):
        """启动 MCP 服务器进程并完成初始化"""
        try:
            self._process = await asyncio.create_subprocess_exec(
                self.command, *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise MCPConnectionError(f"命令 '{self.command}' 未找到，请先安装")

        self._reader = self._process.stdout
        self._writer = self._process.stdin
        self._running = True

        # 后台读取 stderr（防止阻塞）+ 读取 stdout
        asyncio.create_task(self._read_stderr())
        asyncio.create_task(self._read_loop())

        # 初始化握手
        await self._initialize()
        # 发现工具
        await self._discover_tools()

    async def stop(self):
        """停止服务器"""
        self._running = False
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
            except ProcessLookupError:
                pass
            self._process = None

    @property
    def tools(self) -> list[dict]:
        """获取工具的 OpenAI-compatible schema 列表"""
        schemas = []
        for t in self._tool_list:
            name = t["name"]
            schema = t.get("inputSchema", {"type": "object", "properties": {}})

            # MCP 有时用 $schema, 标准化一下
            if "$schema" in schema:
                del schema["$schema"]

            schemas.append({
                "type": "function",
                "function": {
                    "name": f"mcp_{self.name}_{name}",
                    "description": t.get("description", f"[MCP/{self.name}] {name}"),
                    "parameters": schema,
                },
            })
        return schemas

    async def call_tool(self, name: str, arguments: dict) -> str:
        """调用 MCP 工具，返回文本结果"""
        req_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }

        future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        line = json.dumps(payload, ensure_ascii=False) + "\n"
        self._writer.write(line.encode())
        await self._writer.drain()

        try:
            result = await asyncio.wait_for(future, timeout=120)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise MCPToolCallError(f"工具 '{name}' 调用超时")

        # 提取文本和图片内容
        parts = []
        for item in result.get("content", []):
            t = item.get("type", "")
            if t == "text":
                parts.append(item.get("text", ""))
            elif t == "image":
                img_data = item.get("data", "")
                if img_data:
                    parts.append(f"[图片: {item.get('mimeType', 'image/png')} base64数据 {len(img_data)}字符]")
            elif t == "resource":
                r = item.get("resource", {})
                blob = r.get("blob", "")
                if blob:
                    parts.append(f"[资源: {r.get('blobType', 'unknown')} {len(blob)}字符]")
                else:
                    parts.append(str(r))
        return "\n".join(parts)

    # ── 内部方法 ──────────────────────────────

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _initialize(self):
        """MCP 初始化握手 (initialize → initialized)"""
        # 发送 initialize
        resp = await self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "spider", "version": "1.0.0"},
        })
        # 发送 initialized 通知
        self._notify("notifications/initialized")
        return resp

    async def _discover_tools(self):
        """获取服务器提供的工具列表"""
        result = await self._request("tools/list")
        self._tool_list = result.get("tools", [])

    async def _request(self, method: str, params: dict = None) -> dict:
        """发送 JSON-RPC 请求并等待响应"""
        req_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params:
            payload["params"] = params

        future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        line = json.dumps(payload, ensure_ascii=False) + "\n"
        self._writer.write(line.encode())
        await self._writer.drain()

        try:
            return await asyncio.wait_for(future, timeout=15)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise MCPConnectionError(f"{method} 请求超时")

    def _notify(self, method: str, params: dict = None):
        """发送 JSON-RPC 通知（无响应）"""
        payload = {"jsonrpc": "2.0", "method": method}
        if params:
            payload["params"] = params
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        self._writer.write(line.encode())

    async def _read_loop(self):
        """持续读取 stdout 的 JSON-RPC 响应（支持大负载）"""
        buffer = ""
        decoder = json.JSONDecoder()
        try:
            while self._running and self._reader:
                chunk = await self._reader.read(65536)
                if not chunk:
                    break
                buffer += chunk.decode()

                # 从缓冲区中提取所有完整的 JSON 消息
                while buffer.strip():
                    buffer = buffer.lstrip()
                    try:
                        msg, idx = decoder.raw_decode(buffer)
                        buffer = buffer[idx:]
                    except json.JSONDecodeError:
                        break  # 需要更多数据

                    msg_id = msg.get("id")
                    if msg_id is not None and msg_id in self._pending:
                        future = self._pending.pop(msg_id)
                        if "result" in msg:
                            future.set_result(msg["result"])
                        elif "error" in msg:
                            future.set_exception(
                                MCPToolCallError(msg["error"].get("message", "未知错误"))
                            )
        except Exception as e:
            logger.debug(f"[MCP/{self.name}] 读取循环结束: {e}")
        finally:
            self._running = False
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(MCPConnectionError("MCP 服务器已断开"))
            self._pending.clear()

    async def _read_stderr(self):
        """读取并记录 stderr（防止缓冲区阻塞）"""
        try:
            while self._running and self._process and self._process.stderr:
                line = await self._process.stderr.readline()
                if not line:
                    break
                text = line.decode().strip()
                if text:
                    logger.debug(f"[MCP/{self.name} stderr] {text}")
        except Exception:
            pass


class MCPManager:
    """管理多个 MCP 服务器"""

    def __init__(self, config_path: str = None):
        self._servers: dict[str, MCPServer] = {}
        self._config_path = config_path
        self._loaded = False
        self._loaded_ok = False

    async def load_config(self, config_path: str = None):
        """从 JSON 配置文件加载并启动 MCP 服务器"""
        path = config_path or self._config_path
        if not path or not os.path.exists(path):
            return

        self._config_path = path

        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)

        servers = config.get("servers", [])
        if not servers:
            return

        for s in servers:
            if not s.get("enabled", True):
                continue

            server = MCPServer(
                name=s["name"],
                command=s["command"],
                args=s.get("args", []),
            )
            try:
                await server.start()
                self._servers[s["name"]] = server
                count = len(server._tool_list)
                logger.info(f"  🤖 MCP [{s['name']}]: 已连接，{count} 个工具")
            except MCPError as e:
                logger.warning(f"  ⚠️  MCP [{s['name']}]: {e}")

        self._loaded = True
        self._loaded_ok = bool(self._servers)

    async def shutdown(self):
        """关闭所有 MCP 服务器"""
        for server in self._servers.values():
            await server.stop()
        self._servers.clear()

    def register_to(self, registry):
        """将 MCP 工具注册到 ToolRegistry"""
        for server_name, server in self._servers.items():
            for tool_info in server._tool_list:
                tool_name = tool_info["name"]
                handler = self._make_handler(server_name, tool_name)

                schema = tool_info.get("inputSchema", {"type": "object", "properties": {}})
                if "$schema" in schema:
                    del schema["$schema"]

                mcp_name = f"mcp_{server_name}_{tool_name}"
                description = tool_info.get(
                    "description",
                    f"[MCP/{server_name}] {tool_name}",
                )

                registry.register(mcp_name, f"[MCP] {description}", handler, schema)

    def _make_handler(self, server_name: str, tool_name: str):
        """创建 MCP 工具调用 handler"""
        async def handler(**kwargs):
            server = self._servers[server_name]
            try:
                return await server.call_tool(tool_name, kwargs)
            except MCPError as e:
                return f"❌ [MCP/{server_name}/{tool_name}] {e}"

        handler.__name__ = f"mcp_{server_name}_{tool_name}"
        return handler

    def tool_count(self) -> int:
        """统计所有 MCP 服务器的工具总数"""
        total = 0
        for server in self._servers.values():
            total += len(server._tool_list)
        return total

    def summary(self) -> str:
        """返回连接摘要"""
        parts = []
        for name, server in self._servers.items():
            parts.append(f"{name}({len(server._tool_list)} tools)")
        return ", ".join(parts) if parts else "无"
