"""P7-D1 统一数据层控制面（Data Readiness + Gap + Acquisition Planning）。

只读、确定性、零 LLM、零网络、零写入（除 run artifacts 持久化）。
不执行 AcquisitionPlan（执行属于 P7-D2）。
"""

from research_os.data_layer.collector_bridge import (
    CollectorBridgeError,
    CollectorFetcherBridge,
)

__all__ = ["CollectorBridgeError", "CollectorFetcherBridge"]
