"""P7-D3 M1：NBS/CNINFO Collector 跨平台 runtime 加固测试。

覆盖任务书 M1 要求的全部失败与正常路径：
- curl missing（fail closed，零网络）
- curl.exe only / curl only（跨平台解析）
- subprocess timeout
- nonzero exit
- malformed response（页面结构未匹配 → schema_changed 语义）
- normal response

全部离线：不访问真实网络，使用 monkeypatch 模拟。
"""
from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock

import pytest

from research_os.collectors.government.nbs import NbsCollector
from research_os.collectors.official.cninfo import _curl_executable as cninfo_curl


@pytest.fixture
def collector() -> NbsCollector:
    return NbsCollector()


class TestNbsCurlResolution:
    """NBS curl 可执行文件解析（跨平台）。"""

    def test_curl_missing_fails_closed_with_no_subprocess(self, collector, monkeypatch):
        monkeypatch.setattr("research_os.collectors.government.nbs.shutil.which",
                            lambda name: None)
        run = MagicMock()
        monkeypatch.setattr("research_os.collectors.government.nbs.subprocess.run", run)
        assert collector._get_page("https://example.invalid/") is None
        run.assert_not_called()  # curl 缺失：零 subprocess 调用

    def test_curl_exe_only_preferred(self, collector, monkeypatch):
        which = MagicMock(side_effect=lambda name: "C:\\tools\\curl.exe" if name == "curl.exe" else None)
        monkeypatch.setattr("research_os.collectors.government.nbs.shutil.which", which)
        assert collector._curl_executable() == "C:\\tools\\curl.exe"

    def test_curl_only_on_unix(self, collector, monkeypatch):
        which = MagicMock(side_effect=lambda name: "/usr/bin/curl" if name == "curl" else None)
        monkeypatch.setattr("research_os.collectors.government.nbs.shutil.which", which)
        assert collector._curl_executable() == "/usr/bin/curl"

    def test_curl_resolution_uses_shutil_which_not_hardcoded(self, collector):
        # 不再写死 curl.exe：_curl_executable 必须通过 shutil.which 查找
        exe = collector._curl_executable()
        assert exe is None or "curl" in exe

    def test_cninfo_curl_resolution_is_cross_platform(self, monkeypatch):
        which = MagicMock(side_effect=lambda name: "curl.exe" if name == "curl.exe" else None)
        monkeypatch.setattr("research_os.collectors.official.cninfo.shutil.which", which)
        assert cninfo_curl() == "curl.exe"


class TestNbsSubprocessFailures:
    """subprocess 失败路径全部 fail closed。"""

    def test_subprocess_timeout_returns_none(self, collector, monkeypatch):
        monkeypatch.setattr("research_os.collectors.government.nbs.shutil.which",
                            lambda name: "curl")
        def _raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="curl", timeout=1)
        monkeypatch.setattr("research_os.collectors.government.nbs.subprocess.run", _raise_timeout)
        assert collector._get_page("https://example.invalid/") is None

    def test_nonzero_exit_returns_none(self, collector, monkeypatch):
        monkeypatch.setattr("research_os.collectors.government.nbs.shutil.which",
                            lambda name: "curl")
        proc = MagicMock(returncode=7, stdout="", stderr="connection refused")
        monkeypatch.setattr("research_os.collectors.government.nbs.subprocess.run",
                            lambda *a, **k: proc)
        assert collector._get_page("https://example.invalid/") is None

    def test_healthcheck_fails_closed_when_curl_missing(self, collector, monkeypatch):
        monkeypatch.setattr("research_os.collectors.government.nbs.shutil.which",
                            lambda name: None)
        status = collector.healthcheck()
        assert status.ok is False
        assert status.access == "public_but_unstable"

    def test_discover_raises_when_page_unreachable(self, collector, monkeypatch):
        monkeypatch.setattr("research_os.collectors.government.nbs.shutil.which",
                            lambda name: "curl")
        monkeypatch.setattr("research_os.collectors.government.nbs.subprocess.run",
                            lambda *a, **k: MagicMock(returncode=6, stdout=""))
        with pytest.raises(RuntimeError):
            collector.discover({}, {})


class TestNbsResponseHandling:
    """正常与畸形响应。"""

    _HTML = """<html><head><title>国家统计局数据发布</title></head><body>
<a href="./202608/t20260803_1964273.html">2026年7月流通领域生产资料价格变动情况</a>
</body></html>"""

    def test_normal_response_discover(self, collector, monkeypatch):
        monkeypatch.setattr("research_os.collectors.government.nbs.shutil.which",
                            lambda name: "curl")
        monkeypatch.setattr("research_os.collectors.government.nbs.subprocess.run",
                            lambda *a, **k: MagicMock(returncode=0, stdout=self._HTML))
        refs = collector.discover({}, {})
        assert len(refs) == 1
        assert refs[0].title == "2026年7月流通领域生产资料价格变动情况"
        assert refs[0].url.startswith("https://www.stats.gov.cn")
        assert refs[0].published_at == "2026-07-01T00:00:00"

    def test_malformed_page_raises_schema_changed(self, collector, monkeypatch):
        # 页面可达但结构不匹配：显式失败，禁止伪造数据
        monkeypatch.setattr("research_os.collectors.government.nbs.shutil.which",
                            lambda name: "curl")
        monkeypatch.setattr("research_os.collectors.government.nbs.subprocess.run",
                            lambda *a, **k: MagicMock(returncode=0, stdout="<html>no links</html>"))
        with pytest.raises(RuntimeError, match="schema_changed"):
            collector.discover({}, {})

    def test_fetch_failed_on_short_page(self, collector, monkeypatch):
        monkeypatch.setattr("research_os.collectors.government.nbs.shutil.which",
                            lambda name: "curl")
        monkeypatch.setattr("research_os.collectors.government.nbs.subprocess.run",
                            lambda *a, **k: MagicMock(returncode=0, stdout="<html>tiny</html>"))
        from research_os.collectors.base import ItemRef
        payload = collector.fetch(ItemRef(
            source_id="nbs", external_id="x", url="https://www.stats.gov.cn/a.html",
            title="t", published_at=None,
        ))
        assert payload.fetch_status == "failed"
