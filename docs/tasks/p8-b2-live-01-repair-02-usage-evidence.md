# P8-B2-LIVE-01-REPAIR-02 — Provider Usage Evidence Extraction Mapping

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE (Sol)

## 1. Problem statement

P8-B2-LIVE-01-RESUME-03 正式 trial 完整执行了 corpus（10/10 sessions、
20/20 provider-backed turns、0 failures），但 PASS gate
`provider_tokens > 0` 未通过：`total_tokens = NOT_REPORTED`。

## 2. Investigation（usage schema identified）

1. **Usage 进入系统的路径**：`OfficialHarnessClient.send_message` 在 turn
   完成后调用 `_extract_usage({"history": history, "listing": listing})`，
   结果放入 `result["operational_metadata"]["usage"]`；trial 的
   `_usage_from_result` / `_usage_components` 读取并累加进
   `counters.provider_tokens` / `input_tokens` / `output_tokens` /
   `cached_tokens`；evidence snapshot 据此报告 token 字段与 budget 利用率。
2. **dsh rc.7 实际 usage schema**（真实运行时观测，session.history / list）：
   `projections.values.tokenUsage`，键名：
   - `uncachedInputTokens`（int）
   - `outputTokens`（int）
   - `cacheReadTokens`（int）
   - `cacheWriteTokens`（int）
   实测值示例：uncached 23201–27672、output 587–1264、cacheRead 10624–15360、
   cacheWrite 0。
3. **当前 `_extract_usage()` 逻辑**：深度遍历 dict/list，只识别
   `{"input_tokens", "output_tokens", "cached_tokens", "total_tokens",
   "cost_usd"}`（snake_case）。
4. **字段被忽略的原因**：dsh 以 camelCase 键名报告 usage，与识别集合不匹配
   → 提取为空 → `NOT_REPORTED`。不是 provider 未报告，是映射缺失。

## 3. Root cause

Usage 提取映射缺口：accepted runtime（dsh rc.7）的 tokenUsage 键名
（`uncachedInputTokens` / `outputTokens` / `cacheReadTokens` /
`cacheWriteTokens`）未被 `_extract_usage` 识别。与 REPAIR-01 同类
（runtime 契约字段与提取层不匹配）。

## 4. Fix（最小 mapping，仅 provider-reported 值）

`src/research_os/agent_runtime/production_runtime.py` 的 `_extract_usage`：
- 深度遍历同时收集 snake_case 字段（原行为不变）与 dsh tokenUsage 字段；
- 当 dsh 字段存在时，确定性映射（只使用 runtime 报告的值，无估算/推断/
  硬编码）：

```
input_tokens      = uncachedInputTokens + cacheReadTokens + cacheWriteTokens
output_tokens     = outputTokens
cached_tokens     = cacheReadTokens + cacheWriteTokens
cache_read_tokens = cacheReadTokens
cache_write_tokens = cacheWriteTokens
total_tokens      = uncachedInputTokens + outputTokens + cacheReadTokens + cacheWriteTokens
```

- 缺失可选字段按 0 处理（仅对缺失项）；无 dsh 字段时保持原行为（返回空或
  snake_case 值）；非数值/布尔值忽略；字符串（唯一可能携带 secret 的位置）
  永不进入 usage 证据。

未修改：trial contract（10 sessions / 20 turns）、acceptance criteria
（`provider_tokens > 0` 保持）、cost controls（max tokens / timeout / retry
不变）、security rules、provider、MCP namespace / tools。

## 5. Tests（新增 `tests/unit/test_p8_b2_usage_evidence.py`，9 个离线测试）

1. dsh 四字段正确映射到证据词汇；
2. total_tokens 遵循任务书公式（uncached + output + cacheRead + cacheWrite）；
3. 缺失可选字段安全处理（cached 组件缺失 → 0）；
4. 零 usage 如实报告 0（不推断）；
5. 无 usage 字段 → 返回空（NOT_REPORTED 路径保留）；
6. 既有 snake_case 字段仍被识别；
7. 非数值/布尔/None 值忽略；
8. 无 secret 暴露（字符串永不进入 usage 证据）；
9. 嵌套 listing 形状（items[].projections.values.tokenUsage）正确。

## 6. Validation（真实运行时，有界单 turn，非 corpus）

- 修复前（RESUME-03）：`EXTRACTED_USAGE: {}` → `total_tokens = NOT_REPORTED`；
- 修复后（同一有界诊断）：`EXTRACTED_USAGE: {"input_tokens": 23201,
  "output_tokens": 587, "cached_tokens": 10624, "cache_read_tokens": 10624,
  "cache_write_tokens": 0, "total_tokens": 23788}` → `PROVIDER_TOKENS > 0: True`。
- trial count / retry / provider boundary 未改。

## 7. 治理发现（budget 与实测用量）

实测每 provider-backed turn 用量约 **24k–44k tokens**（含缓存；RESUME-03 期间
观测 uncached 27672 + cacheRead 15360 + output 1264 ≈ 44k/turn）。20 turns
预计总用量 **~480k–880k tokens**，超过冻结的 `max_provider_tokens = 200,000`
（LIVE-00 §5.6 / TrialBudget）。因此即使 usage 提取修复后，下一次正式 trial
将如实报告 budget exhaustion（约第 5–9 turn 触发 `RESOURCE_BUDGET_EXCEEDED`）
→ PARTIAL。**budget 属于冻结 cost control，本任务不得修改**；是否调整
200k 上限属于治理决策（Sol），需在正式 corpus 重新执行前决定。

## 8. LIVE-01 重新执行前提（requirement for LIVE-01 rerun）

1. Sol 验收本 REPAIR-02（usage 提取映射 + 测试）；
2. Sol 就 `max_provider_tokens` 冻结值 vs 实测用量（~24-44k/turn × 20 turns）
   作出治理决定（调整预算或接受 budget exhaustion 语义）；
3. 按 LIVE-00 边界重新执行正式 trial（新 RESUME taskbook）。

## 9. 状态

- P8-B2 保持 `IMPLEMENTED / PARTIAL / NOT ACCEPTED`；不写 `P8-B2 ACCEPTED`。
- 本任务未执行 corpus（有界单 turn 诊断明确标记 REPAIR-02 调查，非计数）。
