from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Skill:
    name: str
    kind: str
    instructions: str


class SkillRegistry:
    def __init__(self, root: Path):
        self.root = root

    def discover(self) -> list[str]:
        return sorted(p.parent.name for p in self.root.glob("*/SKILL.md") if p.is_file())

    def load(self, name: str) -> Skill:
        if name not in self.discover():
            raise KeyError(f"unknown skill: {name}")
        text = (self.root / name / "SKILL.md").read_text(encoding="utf-8")
        kind = "scenario" if name == "stock-research" else "capability"
        return Skill(name=name, kind=kind, instructions=text)
