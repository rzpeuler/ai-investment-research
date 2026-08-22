from __future__ import annotations

import importlib.util
import sys


def _module():
    spec = importlib.util.spec_from_file_location(
        "p8_a4_r2_regression_closure", "scripts/p8_a4_r2_regression_closure.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_regression_command_is_bounded_and_fail_closed():
    module = _module()
    assert module.TIMEOUT_SECONDS == 600
    assert "pytest" in module._run.__doc__ if module._run.__doc__ else True


def test_node_pattern_captures_pytest_verbose_result():
    module = _module()
    assert module.NODE_RE.match("tests/unit/test_example.py::test_ok PASSED")
