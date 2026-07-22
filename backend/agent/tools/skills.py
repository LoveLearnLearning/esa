# backend/agent/tools/skills.py

import re
from pathlib import Path

from backend.agent.tools.tools import tr

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def __parse(path: Path) -> tuple[str, str, str]:
    """
    读一个 skill.md 文件 将文件按规定的格式拆成 (name, description, body) 三个部分

    Args:
        path: Path => 文件路径

    Returns:
        tuple[str, str, str] => (name, description, body)
    """
    text: str = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if m is None:
        raise RuntimeError(
            f"{path.name} 缺少 frontmatter（格式应为 ---\\n...\\n---\\n正文）"
        )

    meta: dict = dict(re.findall(r"(\w+):\s*(.+)", m.group(1)))
    name: str = meta["name"]
    description: str = meta["description"]
    body: str = m.group(2).strip()
    return name, description, body


def list_skills() -> list[Path]:
    """
    列举出 skills 文件夹中现有的 skill

    Returns:
        list[Path] => skills 文件夹中现有的 skill 的路径
    """
    return sorted(path for path in SKILLS_DIR.glob("*.md") if path.name != "SKILLS.md")


def list_skills_detail() -> list[tuple[str, str]]:
    """
    返回 skills 文件夹中现有的 skill 的 name 和 description

    Returns:
        list[tuple[str, str]] | [(name, desc) ,...]
                => name: skill 名称
                   desc: skill 概述
    """

    files: list[Path] = list_skills()
    skills: list[tuple[str, str, str]] = [__parse(file) for file in files]
    return [(name, desc) for name, desc, _ in skills]


def build_skills_context() -> str:
    """构建提供给 Agent 的 skill 名称和描述列表"""
    skills = list_skills_detail()

    if not skills:
        return "暂无可用 skill"

    return "\n".join(f"- {name}  {description}" for name, description in skills)


def load_skill(name: str) -> str:
    """
    根据 name 找到对应的 skill 文件，返回正文

    Args:
        name: str => skill name

    Returns:
        str       => skill 的正文
               or => skill not found
    """

    for file in list_skills():
        skill_name, _, body = __parse(file)
        if skill_name == name:
            return body

    return f"{name} skill not found!"


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "加载某个技能的详细操作说明",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "技能名称",
                    },
                },
                "required": ["name"],
            },
        },
    }
)
def load_skill_tool(name: str) -> str:
    return load_skill(name)
