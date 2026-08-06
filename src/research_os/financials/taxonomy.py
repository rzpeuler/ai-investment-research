"""财务科目分类（Phase 4 任务书 3.11/Commit 5）。

从 registry/financial_taxonomy.yaml 加载标准科目，映射原始科目名 → 标准科目候选。
映射只产生候选；LLM 不得直接定稿；低置信映射须人工确认（mapping_method=llm_assisted/manual）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml


def _project_root() -> Path:
    env_root = os.environ.get("RESEARCH_PROJECT_PATH")
    if env_root:
        return Path(env_root)
    # 源码布局: src/research_os/financials/ -> 项目根
    return Path(__file__).resolve().parents[3]


_TAXONOMY_PATH = _project_root() / "registry" / "financial_taxonomy.yaml"


class FinancialTaxonomy:
    """财务科目分类加载器与映射器。"""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or _TAXONOMY_PATH)
        self._data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        self.version: str = self._data.get("version", "1.0.0")
        self._by_code: Dict[str, dict] = {}
        self._synonyms: Dict[str, str] = {}
        self._build_index()

    def _build_index(self) -> None:
        subjects = self._data.get("subjects", {})
        # 兼容两种结构：list（[{- code: ...}]）或 dict（{revenue: {...}}）
        if isinstance(subjects, dict):
            items = [dict({"code": code}, **subj) for code, subj in subjects.items()]
        else:
            items = subjects
        for subj in items:
            code = subj["code"]
            self._by_code[code] = subj
            for syn in subj.get("synonyms", []):
                self._synonyms[syn.strip()] = code
            self._synonyms[subj["canonical"].strip()] = code

    @property
    def codes(self) -> List[str]:
        return sorted(self._by_code)

    def lookup(self, label: str) -> Optional[str]:
        """按原始科目名精确查找标准科目代码（无匹配返回 None）。"""
        key = str(label).strip()
        return self._synonyms.get(key)

    def fuzzy_lookup(self, label: str) -> Optional[str]:
        """包含匹配：原始名包含标准科目名，或标准科目名包含原始名。

        仅用于提示候选；结果须经规则或人工确认。
        """
        key = str(label).strip()
        if not key:
            return None
        # 先精确
        hit = self.lookup(key)
        if hit:
            return hit
        # 包含匹配（去空格）
        compact = key.replace(" ", "")
        for syn, code in self._synonyms.items():
            s = syn.replace(" ", "")
            if s and (s in compact or compact in s):
                return code
        return None

    def subject(self, code: str) -> Optional[dict]:
        return self._by_code.get(code)

    def statement_of(self, code: str) -> Optional[str]:
        subj = self._by_code.get(code)
        return subj.get("statement") if subj else None

    def instant_or_duration(self, code: str) -> str:
        subj = self._by_code.get(code)
        return subj.get("instant_or_duration", "duration") if subj else "duration"


_default_taxonomy: Optional[FinancialTaxonomy] = None


def get_taxonomy() -> FinancialTaxonomy:
    global _default_taxonomy
    if _default_taxonomy is None:
        _default_taxonomy = FinancialTaxonomy()
    return _default_taxonomy
