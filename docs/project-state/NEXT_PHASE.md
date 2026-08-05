# 下一阶段（NEXT PHASE）

## 下一阶段：Phase 4 个股研报

- **状态**：等待正式任务书
- **禁止提前实现**：在正式任务书下达前，不得开始任何 Phase 4 相关实现

## Phase 4 预期范围（以正式任务书为准）

- 复用 Phase 3 基础：统一 LLM Client（接入真实 Provider 后可启用 Flash/Pro 路由）、
  日线导入（可研究自动历史行情源验证）、异动分析事件池
- 场景能力：公司基本面/财务/行业/竞争/估值/催化剂/风险的完整研报编排
- 候选接入：真实 LLM Provider 后，Phase 2 语义聚类/预期差评分、Phase 3 原因
  机制摘要与方向验证可升级为模型方案（业务升级路由已就绪）

## 待办提示（Phase 3 遗留，非阻塞）

- 真实 LLM Provider 配置（.env 中 API Key 接入 LlmClient）
- 自动历史日线来源的在线验证与审计（满足任务书 3.5 条件后写入 primary）
- registry/sources.yaml 中 cninfo/nbs/cls 的 status 字段与 CURRENT_STATE 表格
  表述同步（适配器已建立，状态字段待升格）
