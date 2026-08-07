# 下一阶段准入（NEXT PHASE）

## 当前结论

- **Phase 4 engineering foundation：PASS**
- **Phase 4 full research capability：PARTIAL_SUCCESS / READY_FOR_INDEPENDENT_ACCEPTANCE**
- **Phase 5：BLOCKED**

下一步是对 `633cf74` 及其后文档提交做 Phase 4 full capability 独立验收。不得开始 Phase 5 产业图谱实现、图谱本体变更、
自动批准节点/关系或自动写入核心知识图谱。

## Phase 5 解锁条件

只有以下条件同时满足并完成正式复验，才可提出解除 BLOCKED：

1. 统一控制面、晨报 Evidence、Phase 4 完成定义和文档治理问题全部关闭；
2. 全量测试与已配置质量检查通过，或仅剩有证据且不影响核心能力的环境限制；
3. Phase 4 核心语义模块达到最低覆盖，真实 Provider 状态如实记录；
4. Claim/Evidence Validator 无严重缺口，人工财务和派生事件血缘可反查；
5. README、CURRENT_STATE、NEXT_PHASE、KNOWN_LIMITATIONS 和阶段任务书状态一致；
6. 有新的正式 Phase 5 任务书，且不改变工程指南的既有边界。

任何一项不满足，Phase 5 继续 `BLOCKED`。

## Phase 4 独立验收重点

- 复核 600519.SH 与 300750.SZ 的 Task→Plan→Request→Run→Evidence→报告血缘；
- 复核 688981.SH 受控缺失不会被提升为 success；
- 复核 DeepSeek 间歇性超时仍按 8/1 共享预算降级，且日志无凭证泄漏；
- 独立验收通过后再记录验收 SHA，并决定是否把 full capability 改为 PASS；
- 保持分钟行情、自动历史日线、通用 OCR 和深度媒体等未验证能力为明确限制。
