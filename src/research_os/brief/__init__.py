"""Morning/Evening Brief 共享核心（Phase 6B 同构复用）。

evening_brief 与 morning_brief 复用同一信息处理链：采集、标准化、去重、聚类、
分类、过滤、评分、事件合并、Evidence/Claim、渲染、校验。唯一业务差异为
信息采集时间窗口（见 brief.window）。
"""
