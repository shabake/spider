"""
Spider 网络工具 — 搜索 + 网页抓取

提供两个工具：
- web_search: 搜索网络，返回标题+摘要列表
- web_fetch: 抓取网页，返回可读文本内容

依赖（可选）：
  pip install duckduckgo_search httpx
"""

import logging
import re

logger = logging.getLogger("spider")

# ── 搜索引擎 ──────────────────────────────────────────────

try:
    from duckduckgo_search import DDGS
    HAS_DDG = True
except ImportError:
    HAS_DDG = False

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


async def web_search(query: str, max_results: int = 5) -> str:
    """搜索网络，返回相关结果列表

    Args:
        query: 搜索关键词
        max_results: 最大返回结果数（默认 5）

    Returns:
        搜索结果文本，每行一条
    """
    if not query or not query.strip():
        return "❌ 搜索关键词不能为空"

    if HAS_DDG:
        return await _search_ddg(query, max_results)
    elif HAS_HTTPX:
        return await _search_ddg_lite(query, max_results)
    else:
        return "❌ 缺少依赖：pip install duckduckgo_search httpx"


async def _search_ddg(query: str, max_results: int) -> str:
    """DuckDuckGo SDK 搜索"""
    try:
        loop = __import__("asyncio").get_event_loop()

        def search():
            with DDGS() as ddgs:
                results = []
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    })
                return results

        results = await loop.run_in_executor(None, search)

        if not results:
            return "🔍 未找到相关结果"

        lines = [f"🔍 搜索结果 ({len(results)} 条):\n"]
        for i, r in enumerate(results, 1):
            title = r["title"][:80] if r["title"] else "(无标题)"
            snippet = r["snippet"][:200] if r["snippet"] else ""
            lines.append(f"  {i}. {title}")
            if snippet:
                lines.append(f"     {snippet}")
            lines.append(f"     🔗 {r['url']}")
            lines.append("")
        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"DuckDuckGo 搜索失败: {e}")
        return f"❌ 搜索失败: {e}"


async def _search_ddg_lite(query: str, max_results: int) -> str:
    """DuckDuckGo Lite 版（无需 SDK，直接用 HTTP 请求）"""
    if not HAS_HTTPX:
        return "❌ 需要 httpx: pip install httpx"

    try:
        url = "https://html.duckduckgo.com/html/"
        data = {"q": query}

        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.post(url, data=data)
            resp.raise_for_status()

        # 简易解析结果
        text = resp.text
        results = []

        # 匹配 DuckDuckGo 结果条目
        blocks = re.findall(
            r'<a rel="nofollow" class="result__a" href="(.*?)">(.*?)</a>.*?'
            r'<a class="result__snippet" href=".*?">(.*?)</a>',
            text, re.DOTALL
        )

        for url, title, snippet in blocks[:max_results]:
            title = re.sub(r"<[^>]+>", "", title).strip()
            snippet = re.sub(r"<[^>]+>", "", snippet).strip()
            results.append({"title": title, "url": url, "snippet": snippet})

        if not results:
            return "🔍 未找到相关结果"

        lines = [f"🔍 搜索结果 ({len(results)} 条):\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"  {i}. {r['title'][:80]}")
            if r['snippet']:
                lines.append(f"     {r['snippet'][:200]}")
            lines.append(f"     🔗 {r['url']}")
            lines.append("")
        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"DuckDuckGo Lite 搜索失败: {e}")
        return f"❌ 搜索失败: {e}"


# ── 网页抓取 ──────────────────────────────────────────────

async def web_fetch(url: str, max_length: int = 8000) -> str:
    """抓取网页内容，提取可读文本

    Args:
        url: 网页 URL
        max_length: 最大返回字符数（默认 8000）

    Returns:
        网页文本内容
    """
    if not url or not url.strip():
        return "❌ URL 不能为空"

    if not HAS_HTTPX:
        return "❌ 需要 httpx: pip install httpx"

    # 补全 URL
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
            },
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "text" not in content_type and "html" not in content_type:
            return f"📄 内容类型: {content_type}（{len(resp.content)} 字节）"

        text = resp.text

        # 提取可读文本
        readable = _extract_text(text)

        if not readable.strip():
            return "📄 页面无可提取的文本内容"

        # 截断
        if len(readable) > max_length:
            readable = readable[:max_length] + f"\n\n...（共 {len(readable)} 字符，仅显示前 {max_length} 字符）"

        return f"📄 {url}\n\n{readable.strip()}"

    except httpx.TimeoutException:
        return f"❌ 请求超时: {url}"
    except httpx.HTTPStatusError as e:
        return f"❌ HTTP {e.response.status_code}: {url}"
    except Exception as e:
        return f"❌ 抓取失败: {e}"


def _extract_text(html: str) -> str:
    """从 HTML 提取可读文本"""
    # 移除 script 和 style 标签
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<nav[^>]*>.*?</nav>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<footer[^>]*>.*?</footer>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # 替换换行标签为分隔符
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</p>", "\n\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</h[1-6]>", "\n\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<li>", "\n  • ", html, flags=re.IGNORECASE)
    html = re.sub(r"</li>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"</tr>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</td>", " | ", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", "", html)
    html = re.sub(r"&nbsp;", " ", html)
    html = re.sub(r"&amp;", "&", html)
    html = re.sub(r"&lt;", "<", html)
    html = re.sub(r"&gt;", ">", html)
    html = re.sub(r"&quot;", '"', html)
    html = re.sub(r"&#\d+;", "", html)

    # 压缩空白
    lines = []
    for line in html.split("\n"):
        line = line.strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


# ── Tool Schemas ─────────────────────────────────────────────

WEB_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "搜索关键词，如 '2024年苹果财报'",
        },
        "max_results": {
            "type": "integer",
            "description": "最大返回结果数",
            "default": 5,
        },
    },
    "required": ["query"],
}

WEB_FETCH_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "要抓取的网页 URL，如 https://example.com",
        },
        "max_length": {
            "type": "integer",
            "description": "最大返回字符数",
            "default": 8000,
        },
    },
    "required": ["url"],
}
