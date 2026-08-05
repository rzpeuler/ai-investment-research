"""路由包（Phase 1）：数据需求注册表 + 主备路由。"""
from research_os.routing.requirements import (
    DataRequirement,
    DataRequirementRegistry,
)
from research_os.routing.router import Router

__all__ = ["DataRequirement", "DataRequirementRegistry", "Router"]
