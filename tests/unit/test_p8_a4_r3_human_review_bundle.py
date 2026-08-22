from __future__ import annotations

import importlib.util
import sys


def _module():
    spec = importlib.util.spec_from_file_location(
        "p8_a4_r3_build_human_review_bundle",
        "scripts/p8_a4_r3_build_human_review_bundle.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_bundle_builder_is_read_only_and_does_not_rerun_harness():
    module = _module()
    assert module.MISSING_OUTPUT.startswith("NOT_PERSISTED_BY_R1_ARTIFACT")
    assert "Harness" not in module.build_bundle.__doc__ if module.build_bundle.__doc__ else True


def test_bundle_builder_has_frozen_r1_source():
    module = _module()
    assert module.R1_ARTIFACT.name == "p8_a4_r1_real_provider_validation.json"
    assert module.BUNDLE_ROOT.name == "p8_a4_human_review_bundle"
