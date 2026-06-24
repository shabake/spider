# Spider 使用指南

## 快速启动

```bash
cd /Users/mac/Desktop/Project/spider

# 设置 API Key（首次必做）
export DEEPSEEK_API_KEY="sk-xxxx"

# 一键启动 🎯
python3 main.py "你的任务"
```

---

## 三种启动模式

### 模式 0：Web UI 🌐

适合可视化操作，实时看到 Agent 的思考和工具调用过程。

```bash
python3 main.py --web
```

打开浏览器访问 `http://127.0.0.1:8888`，你会看到：

- **聊天界面** — 输入任务，实时流式显示回复
- **工具调用卡片** — 每个工具调用都可展开查看参数和结果
- **对话历史** — 侧边栏列出所有历史对话，可点击回顾
- **深色主题** — 终端风格，护眼

**可选参数：**
```bash
python3 main.py --web --port 8080 --host 0.0.0.0
```

> 提示：需要先安装 `pip3 install fastapi uvicorn --break-system-packages`

### 模式 1：单次任务 🎯

适合问一个问题就结束的场景。

```bash
# 查文件
python3 main.py "当前目录有哪些文件？"

# 查系统
python3 main.py "我的电脑还剩多少磁盘空间？"

# 文件操作
python3 main.py "在桌面创建一个 hello.txt，写入 Hello Spider"

# 文档转换
python3 main.py "把 ~/Desktop/test.docx 转成 PDF"

# 委托子任务
python3 main.py "用 delegate_task 分别查一下系统名称和当前时间"
```

### 模式 2：交互模式 💬

适合连续对话，反复问问题。

```bash
python3 main.py -i
```

进入后可以看到 `🙋` 提示符，支持的命令：

```
🙋 帮我看看当前目录
🙋 检查磁盘空间
🙋 /tools      ← 查看可用工具
🙋 /help       ← 查看帮助
🙋 /quit       ← 退出
```

---

## 传 API Key 的三种方式

### 方式 1：环境变量（推荐）
```bash
export DEEPSEEK_API_KEY="sk-xxxx"
python3 main.py "你的任务"
```

### 方式 2：命令行参数
```bash
python3 main.py --api-key "sk-xxxx" "你的任务"
```

### 方式 3：写入 shell 配置（一劳永逸）
```bash
echo 'export DEEPSEEK_API_KEY="sk-xxxx"' >> ~/.zshrc
source ~/.zshrc
# 之后直接运行即可
python3 main.py "你的任务"
```

---

## 启动后发生什么

```
你输入
  │
  ▼
🧠 Spider — 开始处理任务
==================================
  │
  ├─ 📚 自动匹配技能（如果有匹配的）
  │     └─ 例如 "检查磁盘空间" → 命中 disk-check 技能
  │
  ├─ 💬 LLM 思考... （流式输出）
  │
  ├─ 🔧 调用工具（如有需要）
  │     ├─ shell → 执行命令
  │     ├─ read_file / write_file → 文件操作
  │     ├─ docx_to_pdf / pdf_to_docx → 文档转换
  │     └─ delegate_task → 委托子 Agent
  │
  ├─ 📦 工具返回结果
  │
  └─ 继续思考 → 直到完成
                    │
                    ▼
==================================
✅ 任务完成 (用时 Xs)
最终回复...
```

---

## 示例场景

### 场景 1：日常系统检查
```bash
python3 main.py "检查磁盘空间"
```
自动匹配 `disk-check` 技能 → 执行 `df -h` + `df -hi` → 输出分析报告。

### 场景 2：探索新项目
```bash
python3 main.py "看看 spider 项目有哪些核心模块，每个文件是干什么的"
```
Agent 会先用 `list_files` 看目录结构，再用 `read_file` 读关键文件。

### 场景 3：保存技能
```bash
python3 main.py "查一下系统运行时间，然后把方法保存为技能"
```
Agent 执行 `uptime` → 调用 `save_skill` 工具 → 以后再说"查运行时间"就能自动执行。

### 场景 4：子代理并行查询
```bash
python3 main.py "分别查一下系统版本、磁盘空间、内存使用"
```
主 Agent 创建 3 个子 Agent 并行执行，最后汇总报告。

---

## 可用工具一览

| 工具 | 说明 | 来源 |
|------|------|------|
| `shell` | 执行任何 shell 命令 | 内置 |
| `read_file` | 读取文件内容 | 内置 |
| `write_file` | 写入/创建文件 | 内置 |
| `list_files` | 列出目录内容 | 内置 |
| `docx_to_pdf` | Word 转 PDF | 扩展 |
| `pdf_to_docx` | PDF 转 Word | 扩展 |
| `delegate_task` | 委托子 Agent 执行任务 | Phase 2 |
| `save_skill` | 保存当前方法为技能 | Phase 2 |
| `list_skills` | 列出所有已保存技能 | Phase 2 |
| `recall` | 搜索长期记忆 | Phase 3 |
| `save_memory` | 保存关键信息到记忆 | Phase 3 |
| `conversations` | 查看历史对话记录 | Phase 3 |
| `self_map` | 【自开发】查看项目结构和模块职责 | Phase 3.5 |
| `self_find` | 【自开发】源码语义搜索 | Phase 3.5 |
| `self_validate` | 【自开发】语法检查 | Phase 3.5 |
| `self_review` | 【自开发】git diff 代码审查 | Phase 3.5 |
| `self_edit` | 【自开发】安全修改代码（备份→改→验→回滚） | Phase 3.5 |
| `self_commit` | 【自开发】自动 git add + commit | Phase 3.5 |

---

## 常见问题

### Q: 启动报错 "API Key 无效"
→ API Key 没设置或不对。参考上方"传 API Key 的三种方式"。

### Q: 启动报错 "ModuleNotFoundError"
→ 缺少依赖，运行：
```bash
pip3 install openai pyyaml python-docx PyMuPDF fpdf2 --break-system-packages
```

### Q: 启动后卡住不动
→ 检查网络能否访问 `api.deepseek.com`。可能需要代理。
```bash
curl https://api.deepseek.com/v1/models -H "Authorization: Bearer $DEEPSEEK_API_KEY"
```

---

## 关于开发环境

Spider 项目是在 Claude Code 中开发的。如果你在使用中遇到以下情况：

### 对话变慢了怎么办？

Claude Code 对话太长时会变慢，有两种方式解决：

**方式 1：/compact（推荐）**
```
在输入框输入 /compact
```
Claude Code 会自动压缩对话历史为摘要，保留关键上下文，减轻负担。

**方式 2：新开会话**

如果仍然想新开，不用担心丢失进度。所有项目资产都保存在本地：

```
~/Desktop/Project/spider/
├── main.py              ← 入口（不会丢）
├── core/                ← 全部代码（不会丢）
├── tools/               ← 全部工具（不会丢）
├── skills/              ← 技能文件（不会丢）
├── docs/                ← 全部文档（不会丢）
└── logs/conversations/  ← 开发记录（不会丢）
```

### 新会话如何快速接上

新开 Claude Code 后，直接说：

```
打开 ~/Desktop/Project/spider 项目，
读 docs/README.md 了解架构和当前进度，
然后我们继续开发
```

Claude Code 会读文档，几分钟就回到状态。所有代码、技能、文档都在硬盘上，**不会丢失**。
