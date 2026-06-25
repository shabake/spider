/* Spider Web UI — Claude 风格前端交互 */

let currentAbortController = null;
let currentConvId = null;
let loadingHistory = false;
let confirmResolver = null;  // 用于 Human-in-the-Loop 确认
let streamContent = '';      // 流式内容累积
let isRunning = false;       // 是否正在执行

// ── DOM 引用 ─────────────────────────────────

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const chatArea = $('#chat-area');
const inputArea = $('#task-input');
const sendBtn = $('#send-btn');
const stopBtn = $('#stop-btn');
const convList = $('#conv-list');
const statusDot = $('#status-dot');
const statusText = $('#status-text');
const emptyState = $('#empty-state');

// ── Markdown 配置 ───────────────────────────

marked.setOptions({
    breaks: true,
    gfm: true,
});

// ── SSE 流式聊天 ─────────────────────────────

async function sendTask() {
    const task = inputArea.value.trim();
    if (!task || sendBtn.disabled) return;

    // 取消上一次请求
    if (currentAbortController) {
        currentAbortController.abort();
    }

    setLoading(true);
    hideEmptyState();
    appendMessage('user', task);
    inputArea.value = '';
    inputArea.style.height = 'auto';

    // 添加 assistant 占位
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message assistant';
    msgDiv.id = 'stream-msg';
    const label = document.createElement('div');
    label.className = 'label';
    label.textContent = '🕷️ Spider';
    msgDiv.appendChild(label);
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.id = 'stream-content';
    // 添加打字指示器
    bubble.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
    msgDiv.appendChild(bubble);
    chatArea.appendChild(msgDiv);
    scrollToBottom();

    // 创建 abort controller
    currentAbortController = new AbortController();
    streamContent = '';

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
            streamContent += data;
            // 移除打字指示器
            const typing = content.querySelector('.typing-indicator');
            if (typing) typing.remove();
            // 用 marked 渲染 markdown
            const rendered = marked.parse(streamContent);
            content.innerHTML = rendered;
            // 高亮代码块
            content.querySelectorAll('pre code').forEach((block) => {
                hljs.highlightElement(block);
            });
            scrollToBottom();
            break;
        }

        case 'thinking_done': {
            // 最终内容已在 chunk 中累积，不需要额外处理
            break;
        }

        case 'turn_start': {
            const d = JSON.parse(data);
            const streamMsg = document.getElementById('stream-msg');
            if (streamMsg && d.turn > 0) {
                streamMsg.id = `msg-${Date.now()}`;
            }
            if (d.turn > 0) {
                // 新 turn 显示思考中
                const thinking = document.createElement('div');
                thinking.className = 'message assistant';
                thinking.id = 'thinking-indicator';
                const bubble = document.createElement('div');
                bubble.className = 'bubble';
                bubble.innerHTML = `
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span>🤔 思考中</span>
                        <span style="color:var(--text-muted);font-size:12px;">(第 ${d.turn}/${d.max_turns} 轮)</span>
                        <div class="typing-indicator" style="display:inline-flex;">
                            <span></span><span></span><span></span>
                        </div>
                    </div>
                `;
                thinking.appendChild(bubble);
                chatArea.appendChild(thinking);
                scrollToBottom();
            }
            break;
        }

        case 'tool_call': {
            removeThinking();
            // 移除流式消息的 ID，让它保留
            const streamMsg = document.getElementById('stream-msg');
            if (streamMsg) streamMsg.id = `msg-${Date.now()}`;
            const d = JSON.parse(data);
            appendToolCall(d.name, d.arguments, null);
            break;
        }

        case 'tool_result': {
            const d = JSON.parse(data);
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
            const doneContent = document.getElementById('stream-content');
            if (doneContent) {
                const typing = doneContent.querySelector('.typing-indicator');
                if (typing) typing.remove();
                if (!doneContent.textContent.trim()) {
                    doneContent.textContent = d.content || '(无回复)';
                }
            }
            // 添加完成标记
            const streamMsg = document.getElementById('stream-msg');
            if (streamMsg) {
                streamMsg.id = `msg-${Date.now()}`;
                if (d.elapsed) {
                    const footer = document.createElement('div');
                    footer.className = 'done-badge';
                    footer.innerHTML = `<span class="check">✓</span> 完成 (${d.elapsed})`;
                    streamMsg.appendChild(footer);
                }
            }
            streamContent = '';
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

        case 'confirm': {
            // Human-in-the-Loop: 显示确认对话框
            const d = JSON.parse(data);
            showConfirmDialog(d.message, d.id);
            break;
        }
    }
}

// ── UI 操作 ─────────────────────────────────

function appendMessage(role, text) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    const label = document.createElement('div');
    label.className = 'label';
    label.textContent = role === 'user' ? '🙋 你' : '🕷️ Spider';
    div.appendChild(label);
    const bubble = document.createElement('div');
    bubble.className = 'bubble';

    if (role === 'assistant') {
        // 用 marked 渲染 markdown
        const rendered = marked.parse(text);
        bubble.innerHTML = rendered;
        bubble.querySelectorAll('pre code').forEach((block) => {
            hljs.highlightElement(block);
        });
    } else {
        bubble.textContent = text;
    }

    div.appendChild(bubble);
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
            <div class="result">${result ? escapeHtml(result) : '<span style="color:var(--orange)">⏳ 执行中...</span>'}</div>
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

function hideEmptyState() {
    if (emptyState) emptyState.style.display = 'none';
}

function showError(msg) {
    const div = document.createElement('div');
    div.style.cssText = `
        padding: 10px 16px; background: var(--red); color: #fff;
        border-radius: 8px; margin: 4px 20px 12px; font-size: 13px;
        text-align: center;
    `;
    div.textContent = `❌ ${msg}`;
    chatArea.appendChild(div);
    scrollToBottom();
}

function setLoading(loading) {
    isRunning = loading;
    sendBtn.disabled = loading;
    inputArea.disabled = loading;
    if (loading) {
        sendBtn.classList.add('hidden');
        stopBtn.classList.remove('hidden');
        statusDot.style.background = 'var(--orange)';
        statusText.textContent = '运行中';
    } else {
        sendBtn.classList.remove('hidden');
        stopBtn.classList.add('hidden');
        statusDot.style.background = 'var(--green)';
        statusText.textContent = '就绪';
    }
}

// ── 停止按钮 ─────────────────────────────────

stopBtn.addEventListener('click', function() {
    if (!isRunning) return;
    if (currentAbortController) {
        currentAbortController.abort();
        currentAbortController = null;
    }
    // 移除 thinking indicator
    removeThinking();
    // 显示已取消
    const streamMsg = document.getElementById('stream-msg');
    if (streamMsg) {
        const bubble = streamMsg.querySelector('.bubble');
        if (bubble) {
            const typing = bubble.querySelector('.typing-indicator');
            if (typing) typing.remove();
            const cancelMsg = document.createElement('div');
            cancelMsg.style.cssText = 'color:var(--text-muted);font-style:italic;padding:12px 0;';
            cancelMsg.textContent = '⏹️ 已取消';
            bubble.appendChild(cancelMsg);
        }
        streamMsg.id = `msg-${Date.now()}`;
    }
    setLoading(false);
});

function scrollToBottom() {
    requestAnimationFrame(() => {
        chatArea.scrollTop = chatArea.scrollHeight;
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ── Human-in-the-Loop 确认弹窗 ──────────────

function showConfirmDialog(message, confirmId) {
    const modal = document.getElementById('confirm-modal');
    const msgEl = document.getElementById('confirm-message');
    msgEl.textContent = message;
    modal.style.display = 'flex';

    return new Promise((resolve) => {
        confirmResolver = { confirmId, resolve };

        document.getElementById('confirm-ok').onclick = () => {
            modal.style.display = 'none';
            if (confirmResolver) {
                confirmResolver.resolve(true);
                confirmResolver = null;
            }
            // 发送确认结果回服务器
            sendConfirmResponse(confirmId, true);
        };

        document.getElementById('confirm-cancel').onclick = () => {
            modal.style.display = 'none';
            if (confirmResolver) {
                confirmResolver.resolve(false);
                confirmResolver = null;
            }
            sendConfirmResponse(confirmId, false);
        };
    });
}

async function sendConfirmResponse(confirmId, approved) {
    try {
        await fetch('/api/chat/confirm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirm_id: confirmId, approved }),
        });
    } catch (e) {
        console.error('发送确认响应失败:', e);
    }
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
        convList.innerHTML = '<div style="color:var(--text-muted);font-size:13px;padding:20px 16px;text-align:center;">暂无对话记录<br><span style="font-size:11px;">开始输入任务吧</span></div>';
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

        chatArea.innerHTML = '';
        hideEmptyState();

        for (const msg of conv.messages) {
            if (msg.role === 'user') {
                appendMessage('user', msg.content);
            } else if (msg.role === 'assistant') {
                appendMessage('assistant', msg.content || '(工具调用)');
            }
        }
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
            if (emptyState) emptyState.style.display = '';
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
        } else if (data.strategy_mode) {
            statusDot.className = 'status-dot';
            statusText.textContent = '🧠 战略推理';
        }
        // 设置面板中显示推理模式状态
        const strategyStatus = document.getElementById('strategy-status');
        if (strategyStatus) {
            if (data.strategy_mode) {
                strategyStatus.textContent = '已启用';
                strategyStatus.style.background = 'rgba(188,140,255,0.15)';
                strategyStatus.style.color = 'var(--purple)';
            } else {
                strategyStatus.textContent = 'CLI 模式（--strategy）';
                strategyStatus.style.background = 'var(--bg-tertiary)';
                strategyStatus.style.color = 'var(--text-muted)';
            }
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
