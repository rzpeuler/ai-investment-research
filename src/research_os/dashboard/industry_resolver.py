"""Resolve industries only from accepted current graph/profile authority."""
from __future__ import annotations

import json
from typing import Any, Iterable

from research_os.dashboard.models import IndustryResult
from research_os.dashboard.target_resolver import normalize_mention


class IndustryResolver:
    def __init__(self, db: Any):
        self.db = db

    def _current(self) -> list[dict]:
        rows = self.db.query("""
            SELECT g.node_id, g.name, g.payload FROM graph_nodes g
            JOIN (SELECT node_id, MAX(version) AS version FROM graph_nodes GROUP BY node_id) latest
              ON latest.node_id=g.node_id AND latest.version=g.version
            WHERE g.node_type='Industry' AND g.status='active' AND g.review_status='approved'
        """)
        result = []
        for row in rows:
            try: payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("invalid authoritative GraphNode payload") from exc
            result.append({"industry_id": row["node_id"], "name": row["name"], "payload": payload})
        return result

    def resolve(self, mentions: Iterable[str] = (), authoritative_ids: Iterable[str] = ()) -> IndustryResult:
        try:
            current = self._current()
        except Exception:  # noqa: BLE001 - graph authority unavailable is not ambiguity
            return IndustryResult(status="failure", message="当前行业本体不可用。")
        candidates = []
        mention_values = [str(x).strip() for x in mentions if str(x).strip()]
        if mention_values:
            needles = {normalize_mention(x) for x in mention_values}
            candidates = [x for x in current if normalize_mention(x["name"]) in needles or normalize_mention(x["industry_id"]) in needles]
        else:
            ids = set(authoritative_ids)
            candidates = [x for x in current if x["industry_id"] in ids]
        unique = {x["industry_id"]: x for x in candidates}
        if len(unique) != 1:
            return IndustryResult(status="clarification", message="行业未唯一命中当前已接受本体，请提供唯一行业名称。")
        item = next(iter(unique.values()))
        return IndustryResult(status="resolved", industry_id=item["industry_id"], industry_name=item["name"])
