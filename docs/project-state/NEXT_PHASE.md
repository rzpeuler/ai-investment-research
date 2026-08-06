# 下一阶段（NEXT PHASE）

## 下一阶段：Phase 4 修复与复验

- **状态**：Phase 4 实施完成（18 提交序列），**独立验收未通过前不得声明 PASS**
- **禁止提前实现 Phase 5**：在 Phase 4 独立验收 PASS 前，不得开始任何 Phase 5 实现

## Phase 5 预期范围（以正式任务书为准，当前仅登记边界）

- 产业图谱（知识库层）：节点/边自动批准机制、本体管理、图谱审核流程；
- Phase 4 已允许输出 GraphChange 候选与 knowledge_coordinates，但不得自动写入
  核心产业图谱；任何提前实现改变阶段边界或引入自动核心图谱写入 = BLOCKER。

## 待办提示（Phase 4 遗留，非阻塞）

- **Phase 4 独立验收**：按验收任务书执行（远端基线/Schema 50/迁移 5/财务导入/
  文档/标准化/指标/质量/分部/同行/估值/预测/Phase 3 复用/LLM/报告/Validator/
  CLI/Skill/离线测试/黄金案例 25 类），验收 PASS 前 NEXT_PHASE 保持"Phase 4 修复与复验"
- 真实 LLM Provider 配置（.env 中 API Key 接入 LlmClient；接入后 Flash/Pro 路由生效）
- 自动历史日线/财务来源的在线验证与审计（满足任务书条件后写入 primary）
- registry/sources.yaml 中 cninfo/nbs/cls 的 status 字段与文档表述同步（走正式治理）
- 同行注册表具体公司关系数据登记
