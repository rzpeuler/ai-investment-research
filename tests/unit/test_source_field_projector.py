"""P7-D3 M3：Canonical Field Projection 测试。

覆盖任务书 §21 要求的全部场景（exact registry、fail closed、不可变性）。
全部离线、确定性。
"""
from __future__ import annotations

import pytest

from research_os.data_layer.field_projector import (
    FieldProjectionError,
    FieldProjector,
)


@pytest.fixture
def projector() -> FieldProjector:
    return FieldProjector()


class TestValidProjection:
    def test_valid_nbs_item(self, projector):
        p = projector.project(
            source_id="nbs", data_type="macro_data", raw_category="statistics_release",
            fields={"published_at": "2026-07-01T00:00:00", "title": "x", "url": "u"},
        )
        assert p.evidence == {"publish_date": "2026-07-01T00:00:00"}
        assert p.source_id == "nbs"
        assert p.data_type == "macro_data"
        assert p.raw_category == "statistics_release"
        assert p.source_fields == ("published_at",)

    def test_valid_cninfo_announcement(self, projector):
        p = projector.project(
            source_id="cninfo", data_type="company_announcement",
            raw_category="announcement",
            fields={"publisher": "贵州茅台", "title": "公告", "url": "u"},
        )
        assert p.evidence == {"company": "贵州茅台"}
        assert p.source_fields == ("publisher",)


class TestFailClosed:
    def test_unknown_projection_key(self, projector):
        with pytest.raises(FieldProjectionError, match="unknown projection key"):
            projector.project(
                source_id="nbs", data_type="company_announcement",
                raw_category="announcement", fields={"publisher": "x"},
            )
        with pytest.raises(FieldProjectionError, match="unknown projection key"):
            projector.project(
                source_id="eastmoney", data_type="macro_data",
                raw_category="statistics_release", fields={},
            )

    def test_wrong_raw_category(self, projector):
        with pytest.raises(FieldProjectionError, match="unknown projection key"):
            projector.project(
                source_id="nbs", data_type="macro_data",
                raw_category="other_category", fields={"published_at": "2026-07-01"},
            )

    def test_missing_required_field(self, projector):
        with pytest.raises(FieldProjectionError, match="published_at"):
            projector.project(
                source_id="nbs", data_type="macro_data",
                raw_category="statistics_release", fields={"title": "x"},
            )
        with pytest.raises(FieldProjectionError, match="publisher"):
            projector.project(
                source_id="cninfo", data_type="company_announcement",
                raw_category="announcement", fields={"title": "x"},
            )

    def test_empty_value_fails_closed(self, projector):
        with pytest.raises(FieldProjectionError, match="published_at"):
            projector.project(
                source_id="nbs", data_type="macro_data",
                raw_category="statistics_release",
                fields={"published_at": "   ", "title": "x"},
            )
        with pytest.raises(FieldProjectionError, match="publisher"):
            projector.project(
                source_id="cninfo", data_type="company_announcement",
                raw_category="announcement", fields={"publisher": "", "title": "x"},
            )

    def test_malformed_value_type(self, projector):
        with pytest.raises(FieldProjectionError, match="published_at"):
            projector.project(
                source_id="nbs", data_type="macro_data",
                raw_category="statistics_release",
                fields={"published_at": 12345, "title": "x"},
            )

    def test_projection_cannot_fabricate_value(self, projector):
        # 输入缺少 canonical 字段 → 投影失败，绝不凭空生成值
        with pytest.raises(FieldProjectionError):
            projector.project(
                source_id="cninfo", data_type="company_announcement",
                raw_category="announcement", fields={"title": "无 publisher"},
            )


class TestImmutability:
    def test_does_not_mutate_input_fields(self, projector):
        fields = {"published_at": "2026-07-01T00:00:00", "title": "x"}
        before = dict(fields)
        projector.project(
            source_id="nbs", data_type="macro_data",
            raw_category="statistics_release", fields=fields,
        )
        assert fields == before

    def test_does_not_mutate_on_failure(self, projector):
        fields = {"title": "x"}
        before = dict(fields)
        with pytest.raises(FieldProjectionError):
            projector.project(
                source_id="cninfo", data_type="company_announcement",
                raw_category="announcement", fields=fields,
            )
        assert fields == before


class TestRegistry:
    def test_registered_keys_exact(self, projector):
        assert projector.registered_keys == (
            ("cninfo", "company_announcement", "announcement"),
            ("nbs", "macro_data", "statistics_release"),
        )

    def test_evidence_fields(self, projector):
        p = projector.project(
            source_id="nbs", data_type="macro_data", raw_category="statistics_release",
            fields={"published_at": "2026-07-01T00:00:00"},
        )
        assert p.evidence_fields == ("publish_date",)
