/* Spider Web UI — 前端交互逻辑 */

let currentAbortController = null;
let currentConvId = null;
let loadingHistory = false;

// ── DOM 引用 ─────────────────────────────────

const $ = (s) => document.querySelector(s);
const chatArea = $('#chat-area');
const inputArea = $('#task-input');
const sendBtn = $('#send-btn');
const convList = $('#conv-list');
const statusDot = $('#status-dot');
const statusText = $('#status-text');

// ── SSE 流式聊天 ─────────────────────────────

async function sendTask() {
    const task = inputArea.value.trim();
    if (!task || sendBtn.disabled) return;

    // 取消上一次请求
    if (currentAbortController) {
        currentAbortController.abort();
    }

    setLoading(true);
    appendMessage('user', task);
    inputArea.value = '';
    inputArea.style.height = 'auto';

    // 添加 assistant 占位
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message assistant';
    msgDiv.id = 'stream-msg';
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.id = 'stream-content';
    msgDiv.appendChild(bubble);
    chatArea.appendChild(msgDiv);
    scrollToBottom();

    // 创建 abort controller
    currentAbortController = new AbortController();

    try {
        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task }),
            signal: currentAbortController.signal,
        });

        if (!response.ok) {
            const err = await response.json();
            showError(err.error || '请求失败');
            return;
        }

        // 读取 SSE 流
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            let eventType = '';
            let eventData = '';

            for (const line of lines) {
                if (line.startsWith('event: ')) {
                    eventType = line.slice(7).trim();
                } else if (line.startsWith('data: ')) {
                    eventData = line.slice(6).trim();
                } else if (line === '') {
                    // 空行 = 事件结束
                    if (eventType && eventData) {
                        handleSSEEvent(eventType, eventData);
                    }
                    eventType = '';
                    eventData = '';
                }
            }
        }
    } catch (err) {
        if (err.name === 'AbortError') return;
        showError(`连接错误: ${err.message}`);
    } finally {
        setLoading(false);
        currentAbortController = null;
    }
}

function handleSSEEvent(type, data) {
    const content = document.getElementById('stream-content');
    if (!content) return;

    switch (type) {
        case 'thinking_chunk': {
            // HTML 转义后追加
            const escaped = escapeHtml(data);
            // 移除光标再追加
            const cursorIdx = content.innerHTML.lastIndexOf('<span class="cursor"></span>');
            if (cursorIdx !== -1) {
                content.innerHTML = content.innerHTML.slice(0, cursorIdx);
            }
            content.innerHTML += escaped;
            content.innerHTML += '<span class="cursor"></span>';
            scrollToBottom();
            break;
        }

        case 'thinking_done': {
            // 移除光标
            const cursorIdx = content.innerHTML.lastIndexOf('<span class="cursor"></span>');
            if (cursorIdx !== -1) {
                content.innerHTML = content.innerHTML.slice(0, cursorIdx);
            }
            break;
        }

        case 'turn_start': {
            const d = JSON.parse(data);
            // 移除流式消息，显示思考中
            const streamMsg = document.getElementById('stream-msg');
            if (streamMsg && d.turn > 0) {
                streamMsg.id = `msg-${Date.now()}`;
            }
            // 新 turn 的思考气泡
            if (d.turn > 0) {
                const thinking = document.createElement('div');
                thinking.className = 'thinking-bubble';
                thinking.id = 'thinking-indicator';
                thinking.innerHTML = `
                    <span>🕷️ 思考中 (${d.turn}/${d.max_turns})</span>
                    <div class="dot-pulse"><span></span><span></span><span></span></div>
                `;
                chatArea.appendChild(thinking);
                scrollToBottom();
            }
            break;
        }

        case 'tool_call': {
            // 移除思考气泡
            removeThinking();
            const d = JSON.parse(data);
            appendToolCall(d.name, d.arguments, null);
            break;
        }

        case 'tool_result': {
            const d = JSON.parse(data);
            // 更新最后一个 tool call 的结果
            const lastTool = document.querySelector('.tool-call:last-child .tool-call-body');
            if (lastTool) {
                const resultDiv = lastTool.querySelector('.result');
                if (resultDiv) {
                    resultDiv.textContent = d.result;
                    lastTool.classList.add('open');
                }
            }
            scrollToBottom();
            break;
        }

        case 'done': {
            const d = JSON.parse(data);
            removeThinking();
            // 若 stream-bubble 还在，替换内容
            const streamContent = document.getElementById('stream-content');
            if (streamContent) {
                // 移除光标
                const cursorIdx = streamContent.innerHTML.lastIndexOf('<span class="cursor"></span>');
                if (cursorIdx !== -1) {
                    streamContent.innerHTML = streamContent.innerHTML.slice(0, cursorIdx);
                }
                if (!streamContent.textContent.trim()) {
                    streamContent.textContent = d.content || '(无回复)';
                }
            }
            if (d.elapsed) {
                const elapsedDiv = document.createElement('div');
                elapsedDiv.style.cssText = 'font-size:11px;color:var(--text-muted);margin-top:4px;text-align:right;';
                elapsedDiv.textContent = `✅ 完成 (${d.elapsed})`;
                const msg = document.getElementById('stream-msg');
                if (msg) msg.appendChild(elapsedDiv);
            }
            // 重置消息 ID 防止重复
            const streamMsg = document.getElementById('stream-msg');
            if (streamMsg) streamMsg.id = `msg-${Date.now()}`;
            // 刷新对话列表
            refreshConversations();
            break;
        }

        case 'error': {
            removeThinking();
            showError(data);
            const streamMsg = document.getElementById('stream-msg');
            if (streamMsg) streamMsg.remove();
            break;
        }
    }
}

// ── UI 操作 ─────────────────────────────────

function appendMessage(role, text) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.innerHTML = `
        <div class="label">${role === 'user' ? '🙋 你' : '🕷️ Spider'}</div>
        <div class="bubble">${escapeHtml(text)}</div>
    `;
    chatArea.appendChild(div);
    scrollToBottom();
}

function appendToolCall(name, args, result) {
    const div = document.createElement('div');
    div.className = 'tool-call';
    div.innerHTML = `
        <div class="tool-call-header" onclick="toggleToolCall(this)">
            <span class="icon">🔧</span>
            <span class="tool-name">${escapeHtml(name)}</span>
            <span class="chevron">▶</span>
        </div>
        <div class="tool-call-body">
            <div class="args">${escapeHtml(JSON.stringify(args, null, 2))}</div>
            <div class="result-label">📦 结果</div>
            <div class="result">${result ? escapeHtml(result) : '等待中...'}</div>
        </div>
    `;
    chatArea.appendChild(div);
    scrollToBottom();
}

function toggleToolCall(header) {
    const body = header.nextElementSibling;
    const chevron = header.querySelector('.chevron');
    body.classList.toggle('open');
    chevron.classList.toggle('open');
}

function removeThinking() {
    const t = document.getElementById('thinking-indicator');
    if (t) t.remove();
}

function showError(msg) {
    const div = document.createElement('div');
    div.style.cssText = `
        padding: 10px 14px; background: var(--red); color: #fff;
        border-radius: 8px; margin-bottom: 12px; font-size: 13px;
        text-align: center;
    `;
    div.textContent = `❌ ${msg}`;
    chatArea.appendChild(div);
    scrollToBottom();
}

function setLoading(loading) {
    sendBtn.disabled = loading;
    sendBtn.textContent = loading ? '处理中...' : '发送';
    inputArea.disabled = loading;
    if (loading) {
        statusDot.className = 'status-dot';
        statusDot.style.background = 'var(--orange)';
        statusText.textContent = '运行中';
    } else {
        statusDot.className = 'status-dot';
        statusDot.style.background = 'var(--green)';
        statusText.textContent = '就绪';
    }
}

function scrollToBottom() {
    chatArea.scrollTop = chatArea.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ── 对话历史 ─────────────────────────────────

async function refreshConversations() {
    try {
        const res = await fetch('/api/conversations');
        if (!res.ok) return;
        const convs = await res.json();
        renderConversationList(convs);
    } catch (e) {
        console.error('加载对话列表失败:', e);
    }
}

function renderConversationList(convs) {
    convList.innerHTML = '';
    if (!convs || convs.length === 0) {
        convList.innerHTML = '<div style="color:var(--text-muted);font-size:13px;padding:16px;text-align:center;">暂无对话记录</div>';
        return;
    }
    for (const c of convs) {
        const div = document.createElement('div');
        div.className = 'conversation-item';
        if (currentConvId === c.id) div.classList.add('active');
        div.innerHTML = `
            <div class="summary">${escapeHtml(c.summary || '(空)')}</div>
            <div class="meta">${c.turn_count} 轮 · ${c.created_at}</div>
            <button class="delete-btn" data-id="${c.id}" title="删除">✕</button>
        `;
        div.addEventListener('click', (e) => {
            if (e.target.classList.contains('delete-btn')) return;
            loadConversation(c.id);
        });
        const delBtn = div.querySelector('.delete-btn');
        delBtn.addEventListener('click', async (e) => {
            e.stopPropagation();
            await deleteConversation(c.id);
        });
        convList.appendChild(div);
    }
}

async function loadConversation(id) {
    if (loadingHistory) return;
    loadingHistory = true;
    try {
        const res = await fetch(`/api/conversations/${id}`);
        if (!res.ok) return;
        const conv = await res.json();
        currentConvId = id;

        // 清空聊天区
        chatArea.innerHTML = '';
        for (const msg of conv.messages) {
            if (msg.role === 'user') {
                appendMessage('user', msg.content);
            } else if (msg.role === 'assistant') {
                appendMessage('assistant', msg.content);
            } else if (msg.role === 'tool') {
                // 工具结果 — 依附上一条 assistant
            }
        }
        // 更新侧边栏 active
        document.querySelectorAll('.conversation-item').forEach(el => el.classList.remove('active'));
        const activeItem = document.querySelector(`.conversation-item .summary`).closest('.conversation-item');
        // 通过 data 标记来高亮
        highlightConvItem(id);
        scrollToBottom();
    } catch (e) {
        console.error('加载对话失败:', e);
    } finally {
        loadingHistory = false;
    }
}

function highlightConvItem(id) {
    document.querySelectorAll('.conversation-item').forEach(el => {
        el.classList.toggle('active', parseInt(el.querySelector('.delete-btn')?.dataset.id) === id);
    });
}

async function deleteConversation(id) {
    try {
        await fetch(`/api/conversations/${id}`, { method: 'DELETE' });
        if (currentConvId === id) {
            currentConvId = null;
            chatArea.innerHTML = '';
        }
        refreshConversations();
    } catch (e) {
        console.error('删除失败:', e);
    }
}

// ── 初始化 ─────────────────────────────────

async function init() {
    // 加载对话列表
    await refreshConversations();

    // 检查状态
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        if (!data.api_key_configured) {
            statusDot.className = 'status-dot error';
            statusText.textContent = '未设置 API Key';
        }
    } catch (e) {
        statusDot.className = 'status-dot disconnected';
        statusText.textContent = '断开';
    }

    // 发送按钮
    sendBtn.addEventListener('click', sendTask);

    // Enter 发送，Shift+Enter 换行
    inputArea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendTask();
        }
    });

    // 自动调整 textarea 高度
    inputArea.addEventListener('input', () => {
        inputArea.style.height = 'auto';
        inputArea.style.height = Math.min(inputArea.scrollHeight, 150) + 'px';
    });
}

document.addEventListener('DOMContentLoaded', init);
