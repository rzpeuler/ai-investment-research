"""Authoritative exact-match company/security resolver."""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Iterable

from research_os.dashboard.models import ResolutionResult


_SYMBOL = re.compile(r"^\d{6}\.(SH|SZ|BJ)$", re.IGNORECASE)
_BARE = re.compile(r"^\d{6}$")
_ENTITY_ONLY = {"stock_review", "stock_research_report", "abnormal_move_analysis"}


def normalize_mention(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return "".join(value.split()).casefold()


class ResearchTargetResolver:
    def __init__(self, db: Any):
        self.db = db

    def _profiles(self) -> tuple[list[dict], list[dict]]:
        companies = []
        securities = []
        for row in self.db.query("SELECT payload FROM company_profiles WHERE status = 'active'"):
            try: companies.append(json.loads(row["payload"]))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("invalid authoritative CompanyProfile payload") from exc
        for row in self.db.query(
            "SELECT payload FROM security_profiles WHERE status IN ('listed', 'suspended')"
        ):
            try: securities.append(json.loads(row["payload"]))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("invalid authoritative SecurityProfile payload") from exc
        return companies, securities

    def is_exact_authoritative_name(self, value: str) -> bool:
        needle = normalize_mention(value)
        try:
            companies, securities = self._profiles()
        except Exception:  # noqa: BLE001 - route probe is boolean; resolution reports failure later
            return False
        names = [p.get("canonical_name", "") for p in companies]
        for profile in securities:
            names.append(profile.get("current_name", ""))
            names.extend(item.get("name", "") for item in profile.get("former_names", []))
        return any(normalize_mention(name) == needle for name in names if name)

    def resolve(self, mentions: Iterable[str], scenario: str) -> ResolutionResult:
        try:
            return self._resolve(mentions, scenario)
        except Exception:  # noqa: BLE001 - authority failure must be explicit and non-leaking
            return ResolutionResult(status="failure", message="权威公司/证券画像当前不可用。")

    def _resolve(self, mentions: Iterable[str], scenario: str) -> ResolutionResult:
        values = [str(v).strip() for v in mentions if str(v).strip()]
        if len(values) != 1:
            return ResolutionResult(status="clarification", message="请只提供一个明确的公司或证券目标。")
        raw = values[0]
        if _SYMBOL.fullmatch(raw):
            symbol = raw.upper()
            if scenario in _ENTITY_ONLY:
                return ResolutionResult(status="resolved", entity=symbol, symbol=symbol)
        companies, securities = self._profiles()
        if _SYMBOL.fullmatch(raw):
            symbol = raw.upper()
            return self._finish(
                [], [s for s in securities if s.get("symbol", "").upper() == symbol],
                companies, securities,
            )
        if _BARE.fullmatch(raw):
            hits = [s for s in securities if str(s.get("symbol", "")).startswith(raw + ".")]
            return self._finish([], hits, companies, securities)
        needle = normalize_mention(raw)
        company_hits = [c for c in companies if normalize_mention(c.get("canonical_name", "")) == needle]
        security_hits = []
        for sec in securities:
            names = [sec.get("current_name", "")]
            names.extend(item.get("name", "") for item in sec.get("former_names", []))
            if any(normalize_mention(name) == needle for name in names if name):
                security_hits.append(sec)
        return self._finish(company_hits, security_hits, companies, securities)

    def _finish(self, company_hits, security_hits, companies, securities) -> ResolutionResult:
        identities: dict[tuple[str, str | None], tuple[dict | None, dict | None]] = {}
        for sec in security_hits:
            company = next((c for c in companies if c.get("entity_id") == sec.get("company_entity_id")), None)
            identities[(str(sec.get("company_entity_id")), str(sec.get("security_entity_id")))] = (company, sec)
        for company in company_hits:
            linked = [s for s in securities if s.get("company_entity_id") == company.get("entity_id")]
            if len(linked) == 1:
                identities[(str(company.get("entity_id")), str(linked[0].get("security_entity_id")))] = (company, linked[0])
            elif not linked:
                identities[(str(company.get("entity_id")), None)] = (company, None)
            else:
                for sec in linked:
                    identities[(str(company.get("entity_id")), str(sec.get("security_entity_id")))] = (company, sec)
        if len(identities) != 1:
            return ResolutionResult(status="clarification", message="目标未唯一命中权威画像，请补充完整证券代码或精确公司名。")
        company, sec = next(iter(identities.values()))
        return ResolutionResult(
            status="resolved", entity=(sec or {}).get("symbol") or (company or {}).get("entity_id"),
            symbol=(sec or {}).get("symbol"), company_entity_id=(company or {}).get("entity_id") or (sec or {}).get("company_entity_id"),
            security_entity_id=(sec or {}).get("security_entity_id"), company_name=(company or {}).get("canonical_name"),
            industry_ids=tuple(dict.fromkeys((company or {}).get("industry_ids", []))),
        )
