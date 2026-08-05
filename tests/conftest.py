"""pytest 全局配置：确保项目根与 src/ 在 sys.path（tests 包导入用）。

注：pytest 9 不再应用 pyproject [tool.pytest.ini_options] 的 pythonpath，
因此在此显式注入 src/，保证测试运行在源码版本而非 site-packages 安装版。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
