"""
Spider 技能系统 (Skill Manager)

类比 Hermes 的 skills 系统：
- 将有效经验保存为技能文件
- 根据任务自动匹配已有技能
- 技能包含：名称、描述、触发器、提示词、所需工具

技能文件存储在 skills/ 目录，YAML 格式。
"""

import os
import re
from datetime import datetime

try:
    import yaml
except ImportError:
    yaml = None


class Skill:
    """单个技能的定义"""

    def __init__(self, name: str, description: str, trigger: str,
                 prompt: str, tools: list[str] = None,
                 created: str = None, file_path: str = None):
        self.name = name
        self.description = description
        self.trigger = trigger          # 关键词匹配模式，如 "磁盘|disk|空间"
        self.prompt = prompt
        self.tools = tools or []
        self.created = created or datetime.now().strftime("%Y-%m-%d")
        self.file_path = file_path

    def matches(self, task: str) -> bool:
        """检查任务是否匹配此技能的 trigger"""
        if not self.trigger:
            return False
        patterns = self.trigger.split("|")
        task_lower = task.lower()
        for p in patterns:
            p = p.strip().lower()
            if p and p in task_lower:
                return True
        return False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "trigger": self.trigger,
            "prompt": self.prompt,
            "tools": self.tools,
            "created": self.created,
        }

    @classmethod
    def from_dict(cls, data: dict, file_path: str = None):
        return cls(
            name=data.get("name", "unnamed"),
            description=data.get("description", ""),
            trigger=data.get("trigger", ""),
            prompt=data.get("prompt", ""),
            tools=data.get("tools", []),
            created=data.get("created"),
            file_path=file_path,
        )


class SkillManager:
    """技能管理器 — 加载、匹配、保存、列出技能"""

    def __init__(self, skills_dir: str = None):
        if skills_dir is None:
            skills_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "skills"
            )
        self.skills_dir = skills_dir
        self._skills: list[Skill] = []
        os.makedirs(self.skills_dir, exist_ok=True)
        self.load_all()

    # ── 加载 ────────────────────────────────────────────────

    def load_all(self):
        """加载 skills/ 目录下所有 .yaml 技能文件"""
        self._skills = []
        if not os.path.isdir(self.skills_dir):
            return

        for fname in sorted(os.listdir(self.skills_dir)):
            if not fname.endswith((".yaml", ".yml")):
                continue
            fpath = os.path.join(self.skills_dir, fname)
            try:
                skill = self._load_file(fpath)
                if skill:
                    self._skills.append(skill)
            except Exception as e:
                print(f"  ⚠️  加载技能失败 {fname}: {e}")

    def _load_file(self, fpath: str) -> Skill | None:
        """加载单个技能文件"""
        if yaml:
            with open(fpath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        else:
            data = self._load_yaml_simple(fpath)

        if not data or not isinstance(data, dict):
            return None
        return Skill.from_dict(data, file_path=fpath)

    def _load_yaml_simple(self, fpath: str) -> dict:
        """简易 YAML 解析（不依赖 pyyaml）"""
        data = {}
        current_key = None
        current_value = []

        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.rstrip()
                # 检测新键 (非缩进行)
                if stripped and not stripped[0].isspace():
                    if ":" in stripped:
                        key, _, val = stripped.partition(":")
                        current_key = key.strip()
                        val = val.strip()
                        # 如果有行内值
                        if val and not val.startswith("|"):
                            data[current_key] = val
                            current_key = None
                        elif val == "|":
                            current_value = []
                            data[current_key] = ""
                        else:
                            data[current_key] = val if val else ""
                            current_key = None
                elif current_key and stripped:
                    # 多行值的一部分
                    prev = data.get(current_key, "")
                    data[current_key] = (prev + "\n" + stripped).strip()

        # 类型转换
        if "tools" in data and isinstance(data["tools"], str):
            data["tools"] = [t.strip() for t in data["tools"].strip("[]").split(",") if t.strip()]
        return data

    # ── 匹配 ────────────────────────────────────────────────

    def find_matching(self, task: str) -> list[Skill]:
        """
        根据任务文本匹配技能

        Args:
            task: 用户任务文本

        Returns:
            匹配的技能列表（按匹配度排序）
        """
        matches = []
        for skill in self._skills:
            if skill.matches(task):
                matches.append(skill)
        return matches

    def get_skill_prompts(self, task: str) -> str:
        """
        获取与任务匹配的技能提示词

        Returns:
            拼接后的提示词文本，无匹配返回空字符串
        """
        matches = self.find_matching(task)
        if not matches:
            return ""

        prompts = []
        for skill in matches:
            prompts.append(
                f"📌 参考技能 [{skill.name}]: {skill.description}\n"
                f"{skill.prompt}"
            )

        return "\n\n".join(prompts)

    # ── 保存 ────────────────────────────────────────────────

    async def save(self, name: str, description: str, trigger: str,
                   prompt: str, tools: str = "") -> str:
        """
        保存新技能

        Args:
            name: 技能名称（用作文件名）
            description: 简短描述
            trigger: 触发关键词，用 | 分隔
            prompt: 技能提示词
            tools: 需要的工具，逗号分隔

        Returns:
            保存结果
        """
        # 校验
        if not name or not name.strip():
            return "❌ 技能名称不能为空"
        if not prompt or not prompt.strip():
            return "❌ 技能提示词不能为空"

        name = name.strip().lower().replace(" ", "-")
        fname = f"{name}.yaml"
        fpath = os.path.join(self.skills_dir, fname)

        # 检查是否已存在
        if os.path.exists(fpath):
            return f"❌ 技能 '{name}' 已存在，可用不同名称保存"

        tool_list = [t.strip() for t in tools.split(",") if t.strip()] if tools else []

        skill_data = {
            "name": name,
            "description": description.strip(),
            "trigger": trigger.strip(),
            "prompt": prompt.strip(),
            "tools": tool_list,
            "created": datetime.now().strftime("%Y-%m-%d"),
        }

        try:
            if yaml:
                with open(fpath, "w", encoding="utf-8") as f:
                    yaml.dump(skill_data, f, default_flow_style=False,
                              allow_unicode=True, sort_keys=False)
            else:
                self._save_yaml_simple(fpath, skill_data)
            # 重新加载
            self.load_all()
            return f"✅ 技能 '{name}' 已保存 ({fpath})"
        except Exception as e:
            return f"❌ 保存技能失败: {e}"

    def _save_yaml_simple(self, fpath: str, data: dict):
        """简易 YAML 写入"""
        lines = []
        for k, v in data.items():
            if isinstance(v, list):
                lines.append(f"{k}: [{', '.join(v)}]")
            elif isinstance(v, str) and "\n" in v:
                lines.append(f"{k}: |")
                for line in v.split("\n"):
                    lines.append(f"  {line}")
            else:
                lines.append(f"{k}: {v}")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # ── 查询 ────────────────────────────────────────────────

    def list(self) -> str:
        """列出所有技能"""
        if not self._skills:
            return "📭 暂无技能，完成任务后可以用 save_skill 保存"

        lines = [f"📚 已加载 {len(self._skills)} 个技能:\n"]
        for skill in self._skills:
            lines.append(f"  🏷️  {skill.name}")
            lines.append(f"     {skill.description}")
            lines.append(f"     📎 触发: {skill.trigger}")
            if skill.tools:
                lines.append(f"     🛠️  工具: {', '.join(skill.tools)}")
            lines.append("")
        return "\n".join(lines)

    def get_names(self) -> list[str]:
        """获取所有技能名称"""
        return [s.name for s in self._skills]


# ── Tool Schemas ─────────────────────────────────────────

SAVE_SKILL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "技能名称（用作文件名，如 disk-check）",
        },
        "description": {
            "type": "string",
            "description": "简短描述这个技能做什么",
        },
        "trigger": {
            "type": "string",
            "description": "触发关键词，用 | 分隔，如 '磁盘|disk|空间|存储'",
        },
        "prompt": {
            "type": "string",
            "description": "技能的完整提示词，告诉 AI 应该怎么做",
        },
        "tools": {
            "type": "string",
            "description": "需要的工具，逗号分隔，如 'shell, read_file'",
        },
    },
    "required": ["name", "description", "trigger", "prompt"],
}

LIST_SKILLS_SCHEMA = {
    "type": "object",
    "properties": {},
}
