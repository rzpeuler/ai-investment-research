"""P7-D3 M2：SourceQueryProjector 测试。

覆盖任务书 §20 要求的全部场景（含 fail closed 语义与输入不可变性）。
全部离线、确定性。
"""
from __future__ import annotations

import pytest

from research_os.data_layer.source_query_projector import (
    SourceQueryProjectionError,
    SourceQueryProjector,
)

# 权威映射（测试注入）：entity_id -> symbol
_SECURITIES = {
    "company:maotai": "600519.SH",
    "company:catl": "300750.SZ",
    "company:beijing": "430047.BJ",   # 北交所：CNINFO 不支持
    "company:malformed": "60051X.SH",  # malformed symbol
    "company:ambiguous-a": "000001.SZ",  # 两个 security 指向同一 entity → ambiguous
    "company:ambiguous-b": "000001.SZ",
}


def _resolver(entity_id: str):
    # 歧义（多个 security 指向同一 company_entity_id）：resolver 检测后返回 None（无唯一结果）
    if entity_id in ("company:ambiguous-a", "company:ambiguous-b"):
        return None
    return _SECURITIES.get(entity_id)


@pytest.fixture
def projector() -> SourceQueryProjector:
    return SourceQueryProjector(security_resolver=_resolver)


@pytest.fixture
def window():
    return {"start": "2026-08-01T00:00:00+08:00", "end": "2026-08-16T00:00:00+08:00"}


class TestValidProjection:
    def test_valid_shanghai_security(self, projector, window):
        q = projector.project(
            source_id="cninfo", data_type="company_announcement",
            canonical_query={"entity_ids": ["company:maotai"]}, time_window=window,
        )
        assert q == {"stock": "600519"}

    def test_valid_shenzhen_security(self, projector, window):
        q = projector.project(
            source_id="cninfo", data_type="company_announcement",
            canonical_query={"entity_ids": ["company:catl"]}, time_window=window,
        )
        assert q == {"stock": "300750"}

    def test_nbs_projects_empty_query(self, projector, window):
        q = projector.project(
            source_id="nbs", data_type="macro_data",
            canonical_query={"entity_ids": []}, time_window=window,
        )
        assert q == {}

    def test_cninfo_empty_entity_ids_global_query(self, projector, window):
        q = projector.project(
            source_id="cninfo", data_type="company_announcement",
            canonical_query={"entity_ids": []}, time_window=window,
        )
        assert q == {}


class TestFailClosed:
    def test_unknown_source(self, projector, window):
        with pytest.raises(SourceQueryProjectionError):
            projector.project(
                source_id="eastmoney", data_type="company_announcement",
                canonical_query={}, time_window=window,
            )

    def test_unknown_data_type(self, projector, window):
        with pytest.raises(SourceQueryProjectionError):
            projector.project(
                source_id="cninfo", data_type="market_daily_ohlcv",
                canonical_query={}, time_window=window,
            )

    def test_wrong_source_data_type_pair(self, projector, window):
        # nbs 只登记 macro_data；cninfo 只登记 company_announcement
        with pytest.raises(SourceQueryProjectionError):
            projector.project(
                source_id="nbs", data_type="company_announcement",
                canonical_query={}, time_window=window,
            )
        with pytest.raises(SourceQueryProjectionError):
            projector.project(
                source_id="cninfo", data_type="macro_data",
                canonical_query={}, time_window=window,
            )

    def test_unknown_entity(self, projector, window):
        with pytest.raises(SourceQueryProjectionError, match="无权威 security 映射"):
            projector.project(
                source_id="cninfo", data_type="company_announcement",
                canonical_query={"entity_ids": ["company:unknown"]}, time_window=window,
            )

    def test_entity_with_no_security_resolver(self, window):
        # 未注入 resolver → fail closed
        bare = SourceQueryProjector()
        with pytest.raises(SourceQueryProjectionError, match="security resolver"):
            bare.project(
                source_id="cninfo", data_type="company_announcement",
                canonical_query={"entity_ids": ["company:maotai"]}, time_window=window,
            )

    def test_ambiguous_security_mapping(self, projector, window):
        # 同一 entity 映射到多个 security 时 resolver 必须显式处理；
        # 本投影器只接受唯一确定性结果，未唯一 → fail closed
        with pytest.raises(SourceQueryProjectionError):
            projector.project(
                source_id="cninfo", data_type="company_announcement",
                canonical_query={"entity_ids": ["company:ambiguous-a"]},
                time_window=window,
            )

    def test_malformed_symbol(self, projector, window):
        with pytest.raises(SourceQueryProjectionError, match="malformed"):
            projector.project(
                source_id="cninfo", data_type="company_announcement",
                canonical_query={"entity_ids": ["company:malformed"]},
                time_window=window,
            )

    def test_bj_exchange_not_supported(self, projector, window):
        with pytest.raises(SourceQueryProjectionError, match="不支持交易所"):
            projector.project(
                source_id="cninfo", data_type="company_announcement",
                canonical_query={"entity_ids": ["company:beijing"]},
                time_window=window,
            )

    def test_multiple_entity_ids_fail_closed(self, projector, window):
        with pytest.raises(SourceQueryProjectionError, match="恰好 0 或 1 个"):
            projector.project(
                source_id="cninfo", data_type="company_announcement",
                canonical_query={"entity_ids": ["company:maotai", "company:catl"]},
                time_window=window,
            )

    def test_malformed_canonical_query(self, projector, window):
        with pytest.raises(SourceQueryProjectionError):
            projector.project(
                source_id="cninfo", data_type="company_announcement",
                canonical_query={"entity_ids": "600519"}, time_window=window,
            )
        with pytest.raises(SourceQueryProjectionError):
            projector.project(
                source_id="cninfo", data_type="company_announcement",
                canonical_query={"entity_ids": [123]}, time_window=window,
            )
        with pytest.raises(SourceQueryProjectionError):
            projector.project(
                source_id="nbs", data_type="macro_data",
                canonical_query="not-a-mapping", time_window=window,
            )

    def test_invalid_time_window(self, projector):
        with pytest.raises(SourceQueryProjectionError, match="time_window"):
            projector.project(
                source_id="nbs", data_type="macro_data",
                canonical_query={}, time_window={"start": "not-a-date", "end": None},
            )
        with pytest.raises(SourceQueryProjectionError, match="time_window"):
            projector.project(
                source_id="cninfo", data_type="company_announcement",
                canonical_query={"entity_ids": ["company:maotai"]},
                time_window={"start": "2026-08-16T00:00:00+08:00",
                             "end": "2026-08-01T00:00:00+08:00"},  # end < start
            )
        with pytest.raises(SourceQueryProjectionError, match="time_window"):
            projector.project(
                source_id="nbs", data_type="macro_data",
                canonical_query={}, time_window=None,
            )

    def test_date_only_time_window_fails_closed(self, projector):
        # date-only 边界：按现有时间 authority（validate_iso）处理 —— date-only 非法 → fail closed
        with pytest.raises(SourceQueryProjectionError, match="time_window"):
            projector.project(
                source_id="nbs", data_type="macro_data",
                canonical_query={}, time_window={"start": "2026-08-01", "end": "2026-08-16"},
            )

    def test_timezone_aware_window_is_valid(self, projector):
        q = projector.project(
            source_id="nbs", data_type="macro_data",
            canonical_query={},
            time_window={"start": "2026-08-01T00:00:00+08:00", "end": "2026-08-16T00:00:00Z"},
        )
        assert q == {}


class TestImmutability:
    def test_projector_does_not_mutate_caller_input(self, projector, window):
        canonical = {"entity_ids": ["company:maotai"], "peer_entity_ids": []}
        window_copy = dict(window)
        canonical_copy = dict(canonical)
        projector.project(
            source_id="cninfo", data_type="company_announcement",
            canonical_query=canonical, time_window=window,
        )
        assert canonical == canonical_copy
        assert window == window_copy

    def test_projector_does_not_mutate_on_failure(self, projector, window):
        canonical = {"entity_ids": ["company:unknown"]}
        canonical_copy = dict(canonical)
        with pytest.raises(SourceQueryProjectionError):
            projector.project(
                source_id="cninfo", data_type="company_announcement",
                canonical_query=canonical, time_window=window,
            )
        assert canonical == canonical_copy


class TestRegistry:
    def test_registered_pairs_exact(self, projector):
        assert projector.registered_pairs == (
            ("cninfo", "company_announcement"),
            ("nbs", "macro_data"),
        )
