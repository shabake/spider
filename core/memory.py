"""
Spider 持久化记忆系统

基于 SQLite，提供：
- 对话历史持久化
- FTS5 全文搜索回忆（LIKE fallback）
- 关键记忆存储与检索
- Agent 可通过工具主动 recall / save_memory

用法:
    store = MemoryStore("path/to/spider_memory.db")
    conv_id = store.create_conversation("用户的问题")
    store.save_message(conv_id, "user", "你好")
    store.save_message(conv_id, "assistant", "有什么可以帮你？")
    result = store.recall("磁盘空间")
"""

import json
import os
import sqlite3
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("spider")


# ── 向量工具 ──────────────────────────────────────────

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class MemoryStore:
    """持久化记忆存储"""

    def __init__(self, db_path: Optional[str] = None, llm=None):
        """
        Args:
            db_path: SQLite 文件路径，默认 <项目根>/spider_memory.db
            llm: LLM 实例（用于 embedding），不传则只用关键词搜索
        """
        if db_path is None:
            db_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "spider_memory.db",
            )
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._fts_available = False
        self._llm = llm  # 用于 embedding
        self._embedding_dim = 0  # 检测到第一个 embedding 后记录
        self._init_db()
        logger.info(f"📀 记忆存储已初始化: {db_path}")

    # ── 数据库连接 ──────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_db(self):
        """初始化表结构"""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                summary TEXT DEFAULT '',
                turn_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conv
                ON messages(conversation_id, id);

            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                source_conv_id INTEGER,
                access_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS memory_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id INTEGER NOT NULL UNIQUE,
                embedding BLOB,
                model TEXT DEFAULT '',
                FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
            );
        """)

        # FTS5 全文索引（支持中文）
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(content, category, tokenize='unicode61')
            """)
            self._fts_available = True
        except Exception as e:
            logger.info(f"FTS5 不可用，使用 LIKE 回退: {e}")
            self._fts_available = False

        conn.commit()

    # ── 会话管理 ────────────────────────────────────────────

    def create_conversation(self, summary: str = "") -> int:
        """创建新会话，返回会话 ID"""
        conn = self._get_conn()
        cur = conn.execute(
            "INSERT INTO conversations (summary) VALUES (?)",
            (summary[:200],),
        )
        conn.commit()
        return cur.lastrowid

    def update_conversation(
        self,
        conv_id: int,
        summary: Optional[str] = None,
        turn_count: Optional[int] = None,
    ):
        """更新会话信息"""
        fields = []
        values = []
        if summary is not None:
            fields.append("summary = ?")
            values.append(summary[:200])
        if turn_count is not None:
            fields.append("turn_count = ?")
            values.append(turn_count)
        if fields:
            fields.append("updated_at = datetime('now', 'localtime')")
            values.append(conv_id)
            conn = self._get_conn()
            conn.execute(
                f"UPDATE conversations SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            conn.commit()

    def get_conversation_messages(self, conv_id: int) -> str:
        """将会话消息格式化为可读文本"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT role, content, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY id",
            (conv_id,),
        ).fetchall()
        if not rows:
            return "(空)"
        lines = []
        for r in rows:
            label = {"user": "🙋", "assistant": "🕷️", "tool": "  📦"}.get(
                r["role"], "?"
            )
            content = (r["content"] or "")[:500]
            if content:
                lines.append(f"  {label} {content}")
        return "\n".join(lines)

    async def list_conversations(self, limit: int = 10) -> str:
        """列出最近的对话（Agent 工具）"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, summary, turn_count, created_at FROM conversations "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        if not rows:
            return "📭 暂无对话记录"
        lines = [f"📚 最近 {len(rows)} 条对话:\n"]
        for r in rows:
            lines.append(
                f"  #{r['id']} {r['summary'][:60]}"
                f" — {r['turn_count']}轮 — {r['created_at']}"
            )
        return "\n".join(lines)

    # ── 消息存储 ────────────────────────────────────────────

    def save_message(
        self,
        conv_id: int,
        role: str,
        content: str = "",
        metadata: Optional[dict] = None,
    ):
        """保存单条消息到会话"""
        if content and len(content) > 5000:
            content = content[:5000]
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, metadata) VALUES (?, ?, ?, ?)",
            (conv_id, role, content or "",
             json.dumps(metadata or {}, ensure_ascii=False)),
        )
        conn.commit()

    # ── 记忆检索 (Recall) ────────────────────────────────────

    def recall(self, query: str, category: Optional[str] = None,
               limit: int = 5) -> str:
        """
        搜索相关记忆（Agent 工具 + 自动注入共用）

        同时搜索:
        1. memories 表 — 向量语义搜索 > FTS5 > LIKE
        2. 最近对话消息 — LIKE
        """
        if not query or not query.strip():
            return ""

        results = []

        # 1. 搜索关键记忆（混合：语义 + 关键词）
        seen_ids = set()
        for r in self._search_memories(query, category, limit * 2):
            mem_id = r.get("id")
            if mem_id:
                seen_ids.add(mem_id)
            results.append({
                "content": r["content"],
                "source": f"记忆 ({r['category']})",
                "score": r.get("score", 0.5),
            })

        # 2. 搜索最近对话消息
        for r in self._search_messages(query, limit):
            results.append({
                "content": r["content"],
                "source": f"对话 #{r['conv_id']}",
                "score": r.get("score", 0.3),
            })

        # 去重 & 排序
        seen = set()
        deduped = []
        for r in sorted(results, key=lambda x: -x["score"]):
            key = r["content"][:100]
            if key not in seen:
                seen.add(key)
                deduped.append(r)

        deduped = deduped[:limit]
        if not deduped:
            return ""

        lines = [f"🔍 找到 {len(deduped)} 条相关记忆:\n"]
        for r in deduped:
            lines.append(f"  [{r['source']}] {r['content'][:300]}")
        return "\n".join(lines)

    def _search_memories(self, query: str, category: Optional[str],
                         limit: int) -> list[dict]:
        """
        混合搜索 memories 表：
        1. 语义搜索（向量 + cosine similarity）— 最高优先级
        2. FTS5 全文搜索
        3. LIKE 模糊搜索（保底）
        """
        results = []

        # 1. 语义搜索（有 LLM 时）
        if self._llm:
            semantic = self._search_memories_semantic(query, category, limit)
            results.extend(semantic)

        # 2. FTS5（补充）
        if self._fts_available:
            # 跳过语义已返回的 ID
            seen_ids = {r["id"] for r in results if "id" in r}
            fts = self._search_memories_fts(query, category, limit)
            for r in fts:
                if r.get("id") not in seen_ids:
                    results.append(r)
                    seen_ids.add(r["id"])

        # 3. LIKE（保底）
        if len(results) < limit:
            seen_ids = {r["id"] for r in results if "id" in r}
            like = self._search_memories_like(query, category, limit)
            for r in like:
                if r.get("id") not in seen_ids:
                    results.append(r)

        # 更新访问计数（用于热度排序）
        seen_ids = {r["id"] for r in results if "id" in r}
        if seen_ids:
            try:
                conn = self._get_conn()
                placeholders = ",".join("?" * len(seen_ids))
                conn.execute(
                    f"UPDATE memories SET access_count = access_count + 1 "
                    f"WHERE id IN ({placeholders})",
                    list(seen_ids),
                )
                conn.commit()
            except Exception:
                pass

        return results[:limit]

    def _search_memories_semantic(self, query: str, category: Optional[str],
                                  limit: int) -> list[dict]:
        """
        语义搜索：embedding + cosine similarity

        对查询文本生成向量，与数据库中所有记忆的向量逐条计算相似度，
        返回最相似的 top-k。
        """
        if not self._llm:
            return []

        query_emb = self._llm.get_embedding(query)
        if not query_emb:
            return []

        conn = self._get_conn()
        try:
            sql = """
                SELECT m.id, m.content, m.category, me.embedding
                FROM memory_embeddings me
                JOIN memories m ON me.memory_id = m.id
                WHERE me.embedding IS NOT NULL AND me.embedding != ''
            """
            params = []
            if category:
                sql += " AND m.category = ?"
                params.append(category)

            rows = conn.execute(sql, params).fetchall()

            scored = []
            for r in rows:
                import json
                try:
                    emb = json.loads(r["embedding"])
                    score = cosine_similarity(query_emb, emb)
                    if score > 0.3:  # 相似度阈值
                        scored.append({
                            "id": r["id"],
                            "content": r["content"],
                            "category": r["category"],
                            "score": score,
                        })
                except (json.JSONDecodeError, TypeError):
                    continue

            scored.sort(key=lambda x: -x["score"])
            return scored[:limit]

        except Exception as e:
            logger.debug(f"语义搜索失败: {e}")
            return []

    def _search_memories_fts(self, query: str, category: Optional[str],
                             limit: int) -> list[dict]:
        """FTS5 全文搜索"""
        conn = self._get_conn()
        try:
            safe = query.replace('"', '""')
            sql = """
                SELECT m.id, m.content, m.category, m.access_count, rank
                FROM memories_fts fts
                JOIN memories m ON fts.rowid = m.id
                WHERE memories_fts MATCH ?
            """
            params = [safe]
            if category:
                sql += " AND m.category = ?"
                params.append(category)
            sql += " ORDER BY rank LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            # FTS5 rank 越小越匹配，转换成 0-1 分数
            results = [dict(r) for r in rows]
            if results:
                max_rank = max(r.get("rank", 1) for r in results) or 1
                for r in results:
                    r["score"] = max(0.1, 1.0 - (r.get("rank", 0) / max_rank))
            return results
        except Exception as e:
            logger.debug(f"FTS 搜索失败: {e}")
            return []

    def _search_memories_like(self, query: str, category: Optional[str],
                              limit: int) -> list[dict]:
        """LIKE 模糊搜索（FTS5 后备方案）"""
        conn = self._get_conn()
        keyword = f"%{query}%"
        sql = """
            SELECT id, content, category, access_count
            FROM memories WHERE content LIKE ?
        """
        params = [keyword]
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY access_count DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(r, score=0.5) for r in rows]

    def _search_messages(self, query: str, limit: int) -> list[dict]:
        """搜索最近对话消息（LIKE 模糊匹配）"""
        conn = self._get_conn()
        keyword = f"%{query}%"
        try:
            rows = conn.execute(
                """
                SELECT m.content, m.conversation_id AS conv_id
                FROM messages m
                WHERE m.role IN ('user', 'assistant')
                  AND m.content LIKE ?
                  AND m.content != ''
                ORDER BY m.id DESC
                LIMIT ?
            """,
                (keyword, limit),
            ).fetchall()
            return [dict(r, score=0.3) for r in rows]
        except Exception as e:
            logger.debug(f"消息搜索失败: {e}")
            return []

    # ── 记忆管理 ────────────────────────────────────────────

    async def save_memory(
        self,
        content: str,
        category: str = "general",
        source_conv_id: Optional[int] = None,
    ) -> str:
        """
        保存一条关键记忆（Agent 工具）

        Args:
            content: 记忆内容
            category: 类别 (general|user_pref|project_info|task_result)
            source_conv_id: 来源会话 ID（可选）

        Returns:
            保存结果消息
        """
        if not content or not content.strip():
            return "❌ 记忆内容不能为空"

        valid = {"general", "user_pref", "project_info", "task_result"}
        if category not in valid:
            category = "general"

        content_trimmed = content.strip()[:1000]
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO memories (content, category, source_conv_id) VALUES (?, ?, ?)",
            (content_trimmed, category, source_conv_id),
        )
        conn.commit()

        # 同步到 FTS5
        if self._fts_available:
            try:
                cur = conn.execute("SELECT MAX(id) FROM memories")
                mem_id = cur.fetchone()[0]
                conn.execute(
                    "INSERT INTO memories_fts (rowid, content, category) VALUES (?, ?, ?)",
                    (mem_id, content_trimmed, category),
                )
                conn.commit()
            except Exception as e:
                logger.debug(f"FTS 同步失败: {e}")

        # 同步到向量存储
        if self._llm:
            try:
                embedding = self._llm.get_embedding(content_trimmed)
                if embedding:
                    cur = conn.execute("SELECT MAX(id) FROM memories")
                    mem_id = cur.fetchone()[0]
                    import json
                    blob = json.dumps(embedding)
                    if self._embedding_dim == 0:
                        self._embedding_dim = len(embedding)
                    conn.execute(
                        "INSERT OR REPLACE INTO memory_embeddings (memory_id, embedding, model) VALUES (?, ?, ?)",
                        (mem_id, blob, self._llm.EMBEDDING_MODEL),
                    )
                    conn.commit()
            except Exception as e:
                logger.debug(f"向量同步失败: {e}")

        return f"✅ 已保存记忆 [{category}]: {content_trimmed[:100]}"

    def close(self):
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __del__(self):
        self.close()


# ── Tool Schemas ─────────────────────────────────────────────
# 供 Agent 注册工具时使用

RECALL_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "搜索关键词，如 '磁盘'、'部署'、'用户偏好'",
        },
        "category": {
            "type": "string",
            "description": "过滤类别: general, user_pref, project_info, task_result",
        },
        "limit": {
            "type": "integer",
            "description": "最大返回条数",
            "default": 5,
        },
    },
    "required": ["query"],
}

SAVE_MEMORY_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {
            "type": "string",
            "description": "要记住的信息内容",
        },
        "category": {
            "type": "string",
            "description": "类别: general（通用）, user_pref（用户偏好）, project_info（项目信息）, task_result（任务结果）",
            "default": "general",
        },
    },
    "required": ["content"],
}

LIST_CONVERSATIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "limit": {
            "type": "integer",
            "description": "列出最近多少条对话",
            "default": 10,
        },
    },
}
