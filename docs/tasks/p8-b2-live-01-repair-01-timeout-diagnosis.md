# P8-B2-LIVE-01-REPAIR-01 — Timeout / Harness Recovery Diagnosis

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE (Sol)

## 1. Problem statement

P8-B2-LIVE-01（RESUME-02）正式 trial 首次执行失败：

- trial 前 readiness probe = READY（含 provider connectivity）；
- 第 1 个 provider-backed turn 失败，typed failure = `PROVIDER_TIMEOUT`
  （单次计数，无重试）；
- 随后第 2 个 session create 失败，typed failure = `HARNESS_BOOT_FAILED`
  （adapter.admit：Harness runtime 不再 READY）；
- latch 触发 → fail-closed PARTIAL：completed sessions 0/10、turns 0/20。

表象像 provider 延迟/超时，实际需要查明：turn 为何未完成、Harness 为何退出。

## 2. Observed evidence

### 2.1 Trial evidence（run 32385207624，artifact）

- `typed_failures = {PROVIDER_TIMEOUT: 1, HARNESS_BOOT_FAILED: 1}`
- `session_create_attempts=2, success=1`；`turn_attempts=1, turn_completed=0`
- `process_residue=NO, root_cleanup=TERMINATED, owned_tree_cleanup=VERIFIED`
- `secret_scan=PASS`；drills（rollback/restart/fallback）均 PASS
- 无完成 turn → token/cost NOT_REPORTED

### 2.2 有界单 turn 诊断（REPAIR-01 调查，非 corpus；本地 Windows，真实 provider）

**修复前**（同一 pinned Harness 0.1.0-rc.7）：

```
SESSION_CREATED 141 ms
TURN_FAILED code=PROVIDER_TIMEOUT elapsed=2.6s message='Harness API request failed'
PROCESS_POLL_AFTER 1          ← dsh 进程以 exit code 1 退出
SUPERVISOR_READY False
SUPERVISOR_STATE FAILED
STDERR_TAIL（dsh stderr，节选）:
  Error: dsh: plugin tree failed to load: failed to apply loader entry include
  (cordis:include): failed to apply loader entry research-os-mcp
  (@deepseek-ai/dsh-mcp-client): mcp-client(research_os): initial connection or
  tool synchronization failed
  Error: Server's protocol version is not supported: 1
      at Client.connect (.../@modelcontextprotocol/sdk/dist/esm/client/index.js:294:23)
      ...
  Node.js v24.16.0
```

**修复后**（同一有界诊断）：

```
SESSION_CREATED 156 ms
TURN_COMPLETED 22.7 s "completed"      ← 真实 provider-backed turn 完整成功
PROCESS_POLL_AFTER None                ← 进程存活
SUPERVISOR_READY True
SUPERVISOR_STATE READY
STDERR_TAIL（空）
```

## 3. Root cause analysis

### 3.1 PROVIDER_TIMEOUT 的真实原因 → 分类：Adapter/配置缺陷（我方 MCP server 协议版本协商）

完整链路（代码 + 运行证据）：

1. dsh profile（`agent_runtime/profiles/research-headless/cordis.patch.yml`）把
   `research-os-mcp` 配置为 `@deepseek-ai/dsh-mcp-client`，stdio 拉起
   `python scripts/p8_b1_mcp_server.py`，`failOnStartupError: true`；
2. `dsh-mcp-client` 使用 `@modelcontextprotocol/sdk`（1.30.0），其
   `SUPPORTED_PROTOCOL_VERSIONS = ['2025-11-25','2025-06-18','2025-03-26',
   '2024-11-05','2024-10-07']`；
3. 我方 stdio server 的 initialize 回复 `protocolVersion: "1"`
   （`ResearchOSMCPServer.protocol_version`），SDK 抛
   `"Server's protocol version is not supported: 1"`（client/index.js:294）；
4. `failOnStartupError: true` → 插件树加载失败 → dsh 进程以 exit code 1 崩溃；
5. turn 的 HTTP API 请求打到已死/垂死的 dsh → `OfficialHarnessClient._rpc`
   把连接类错误统一映射为 `PROVIDER_TIMEOUT`（"Harness API request failed"）—
   掩盖了真实原因（进程崩溃），但这是 accepted R2 的故障词汇，本任务不修改。

结论：**不是 provider 延迟问题**。修复后完整 tool-calling turn 仅 22.7s，
远低于 300s turn timeout。真实原因是**我方 MCP stdio server 的协议版本协商
缺陷**导致 pinned Harness 进程崩溃。

### 3.2 HARNESS_BOOT_FAILED → 分类：预期 fail-closed 行为（机制正确，缺陷在 3.1）

- `supervisor.status()`：state=READY 且 `process.poll() is not None`（进程已死）
  → state=FAILED, failure_code=HARNESS_BOOT_FAILED；
- `HarnessAgentRuntimeAdapter.admit()`：`supervisor.ready` False →
  `HARNESS_BOOT_FAILED`；
- trial 的 run_corpus 对 `HARNESS_BOOT_FAILED` 触发 latch → fail-closed 停止。

结论：fail-closed 机制（进程死亡检测 → admit 拒绝 → latch → PARTIAL）按设计
正确工作；`HARNESS_BOOT_FAILED` 是 3.1 崩溃的直接下游结果，不是独立缺陷。
证据完整性（typed 单次计数、无重试、fail-closed snapshot、process cleanup
VERIFIED、secret scan PASS）全部按 R2 语义工作。

## 4. Decision

- **根因**：我方 stdio MCP server 报告 MCP protocol version `"1"`，被 pinned
  Harness 的 MCP SDK 客户端拒绝 → dsh 进程崩溃 → turn 失败（被映射为
  `PROVIDER_TIMEOUT`）→ supervisor FAILED → `HARNESS_BOOT_FAILED`。
- **需要最小修复**：是。修复 MCP 协议版本协商（不修改 acceptance criteria /
  trial contract / failure semantics / Harness / MCP namespace / tools）。
- **修复方案**（最小 targeted patch，2 个文件 + 测试）：
  1. `src/research_os/agent_runtime/mcp/contracts.py`：新增
     `SUPPORTED_MCP_PROTOCOL_VERSIONS`、`DEFAULT_MCP_PROTOCOL_VERSION` 与
     `negotiate_mcp_protocol_version(client_version)` — 客户端版本受支持则
     echo，否则回退到受支持的稳定基线（`2024-11-05`）；
  2. `scripts/p8_b1_mcp_server.py`：initialize 回复使用协商后的
     `protocolVersion`（内部 namespace 契约 `research-os-mcp/v1` 与
     `MCPHandshake.version` 不变）；
  3. `tests/unit/test_p8_b1_mcp_protocol_negotiation.py`：协商逻辑的确定性
     离线测试（echo 支持版本 / "1" 回退 / 缺失回退 / 未知版本回退）。

不做的事：不改 `_rpc` 的故障映射（accepted R2 词汇）；不改 provider；不加
fallback provider；不放松任何 secret/evidence 规则；不改 trial 预算与语义。

## 5. Fix plan（已实施）

见第 4 节；变更文件：

- `src/research_os/agent_runtime/mcp/contracts.py`（+15 行，纯新增函数与常量）
- `scripts/p8_b1_mcp_server.py`（initialize 处理 + import，行为仅 protocolVersion 字段）
- `tests/unit/test_p8_b1_mcp_protocol_negotiation.py`（新增，5 个测试）

## 6. Validation plan（已执行）

1. 有界单 turn 诊断（真实 provider，非 corpus）：
   - 修复前：`TURN_FAILED PROVIDER_TIMEOUT 2.6s` + 进程 exit 1 + supervisor FAILED；
   - 修复后：`TURN_COMPLETED 22.7s "completed"` + 进程存活 + supervisor READY；
2. 单元测试 `test_p8_b1_mcp_protocol_negotiation.py`：5 passed；
3. P8-B2 targeted tests + `test_p8_a0_r2_runtime.py`：全部通过；
4. schema 86/86；compileall PASS；
5. full pytest：见验收报告。

## 7. 重新执行 P8-B2-LIVE-01 的条件

修复满足重新执行条件：同一 pinned Harness 0.1.0-rc.7 在真实 provider 下完成
完整 tool-calling turn 且进程保持 READY（单 turn 22.7s，远低于 300s turn
timeout 与 200,000 token 预算）。正式 10-session / 20-turn corpus 的重新执行
属于新的 LIVE-01 RESUME taskbook（本任务不是正式 trial，未执行 corpus）。

## 8. 状态

- P8-B2 保持 `IMPLEMENTED / PARTIAL / NOT ACCEPTED`；不写 `P8-B2 ACCEPTED`。
- `FORMAL_CORPUS_EXECUTED`：本任务未执行任何 corpus turn（诊断单 turn 明确
  标记为 REPAIR-01 调查，非 session/turn 计数）。
