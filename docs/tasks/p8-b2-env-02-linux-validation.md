# P8-B2-ENV-02 — Linux POSIX Trial Environment Validation

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE (Sol)

本任务在真实 Linux POSIX 环境验证已通过 R2 验收的 P8-B2 environment
readiness implementation（ENV-01 实现 baseline `10199230`），机械验证
process ownership gate：

```
PROCESS_CLEANUP_VERIFIED = YES
PROCESS_RESIDUE = NO
```

目标为 `FORMAL_TRIAL_READY = YES`，或得到真实、可解释的 BLOCKED/FAIL 结果。
本任务不修改 process cleanup implementation、evidence model、acceptance gate、
Harness、MCP 或 Research OS 核心逻辑。

## 策略调整（P8-B2-ENV-02-ADJUST-01）

最初计划使用本地 QEMU + WHPX + Arch Linux VM + MSYS2 QEMU toolchain 建立 Linux
执行环境，该方案已**放弃**。原因（如实记录）：

- 宿主无 WSL 分发版（`Microsoft-Windows-Subsystem-Linux` 为 Disabled，启用需
  重启）、无 Docker；
- 本机国际 CDN 下载被限速（约 10–25KB/s：qemu.weilnetz.de、pkgbuild、
  Alpine CDN、repo.msys2.org 均如此，并行连接无效）；
- 中国镜像（TUNA/USTC）对 HTTPS curl 做 TLS 指纹拦截，明文 HTTP 虽可用，但
  winget 安装 QEMU 因证书错误失败，MSYS2 方案需要新建大量临时工具链；
- accepted R2 Linux process-group 回归测试
  （`tests/unit/test_p8_b2_process_ownership_linux.py`）已在 GitHub Ubuntu CI
  验证 — 复用 GitHub Actions `ubuntu-latest` 作为 Linux POSIX 执行环境，避免
  重复建立本地虚拟化基础设施。

### 本地清理（已完成）

| 资产 | 状态 |
|---|---|
| Arch Linux ISO（1.59GB） | REMOVED |
| MSYS2 base + toolchain（3.3GB，C:\msys64） | REMOVED |
| env02-repo.tar.gz / 下载缓存 / 临时文件 | REMOVED |
| 临时 VM disk / VM 配置文件 | NONE PRODUCED（VM 从未启动） |
| QEMU 安装 | NONE（winget 未完成，Program Files 无 qemu，PATH 无 qemu） |
| 仓库内 VM 资产（*.iso/*.img/*.qcow2/*.vdi/*.vmdk/*.tar.gz/node_modules） | NONE |

`LOCAL_CLEANUP_MANUAL_REQUIRED: NONE`。

## Ubuntu CI validation strategy

新增仅用于 ENV-02 validation 的 workflow：
`.github/workflows/p8-b2-env-02-linux-validation.yml`
（`workflow_dispatch` 触发，不修改生产 `offline-ci.yml`）：

- `ubuntu-latest`（GitHub-hosted Ubuntu，真实 Linux POSIX runner）
- Python 3.12（`actions/setup-python`）
- Node 24（`actions/setup-node`，满足 `@deepseek-ai/dsh` engines >= 24）
- `npm ci` 使用 `agent_runtime/package-lock.json` → pinned `0.1.0-rc.7`
- 执行顺序：
  1. `python -m pytest tests/unit/test_p8_b2_process_ownership_linux.py -q`
  2. `P8_B2_ENV_READINESS=1 PYTHONPATH=src python scripts/p8_b2_env_readiness.py`
  3. `python -m pytest`（full）
  4. `python -m research_os.cli.main validate`
  5. `python -m compileall -q src scripts tests`

### Provider credential handling

- 若 GitHub secret `DEEPSEEK_API_KEY` 已配置：注入探针环境变量，允许执行 bounded
  provider probe（`FORMAL_ACCEPTANCE_TURN = NO`；不输出 key、不写日志、不写
  artifact、不写仓库）。
- 未配置：探针如实报告 `PROVIDER_CREDENTIAL_PRESENT = NO` → `PROVIDER_BLOCKED`，
  不伪造 READY。
- **当前仓库状态：`gh secret list` 为空 — `DEEPSEEK_API_KEY` 未配置。**

## Linux validation evidence

Ubuntu CI workflow run（`P8-B2-ENV-02 Linux Validation`，run ID `32366675372`，
`workflow_dispatch` + branch push 触发，结论 SUCCESS，HEAD `ba59f32`）：

### 环境事实（Ubuntu runner）

| Item | Value |
|---|---|
| OS | Ubuntu 24.04.4 LTS（VERSION_ID 24.04） |
| Kernel | 6.17.0-1022-azure |
| Architecture | x86_64 |
| Python | 3.12.14 |
| Node | v24.19.0 |
| Harness (`dsh --version`) | 0.1.0-rc.7 |

### Readiness probe 结果（`P8_B2_ENV_READINESS=1 PYTHONPATH=src python scripts/p8_b2_env_readiness.py`）

最终结果：**BLOCKED**（唯一原因：GitHub Actions 环境未配置 `DEEPSEEK_API_KEY`
secret — `gh secret list` 为空；按任务书如实报告 `PROVIDER_BLOCKED`，不伪造
READY。探针 exit code = 1，workflow 继续执行后续步骤）。

| Gate | Status | Verdict | Evidence basis |
|---|---|---|---|
| HARNESS_AVAILABLE | YES | READY | OBSERVED |
| HARNESS_VERSION_VERIFIED | YES（0.1.0-rc.7） | READY | OBSERVED |
| PROVIDER_CREDENTIAL_PRESENT | NO | BLOCKED | OBSERVED |
| PROVIDER_CONNECTIVITY_VERIFIED | NOT_VERIFIED | BLOCKED | NOT_VERIFIED |
| RUNTIME_PROFILE_VERIFIED | YES（research-headless） | READY | DERIVED_FROM_OBSERVED_RUNTIME |
| MCP_SERVER_BOOT_VERIFIED | YES | READY | OBSERVED |
| MCP_NAMESPACE_VERIFIED | YES（research-os-mcp/v1） | READY | OBSERVED |
| MCP_TOOLSET_VERIFIED | YES（2 tools，0 unauthorized） | READY | OBSERVED |
| **PROCESS_CLEANUP_VERIFIED** | **YES** | **READY** | OBSERVED |
| SECRET_HYGIENE_VERIFIED | YES（0 markers） | READY | OBSERVED |

**Process ownership（本任务核心）**：

```
ROOT_TERMINATED:      YES
OWNED_TREE_CLEANUP:   VERIFIED
PROCESS_RESIDUE:      NO
PROCESS_CLEANUP_VERIFIED: YES
```

即：在 Ubuntu Linux POSIX 环境，accepted R2 owned process-tree cleanup 机制
（`BoundedOwnedProcess.terminate_tree` + `/proc` PGID 枚举 + `cleanup_status`）
机械证明 owned process group 已清空、无残留 — Windows 宿主无法提供的证据
在 Linux 上已获得。

### 测试（Ubuntu runner 全部步骤 SUCCESS）

- Targeted：`python -m pytest tests/unit/test_p8_b2_process_ownership_linux.py -q`
  → 步骤 SUCCESS（该文件 3 个测试全部执行通过；与全量 pytest 交叉验证一致：
  Ubuntu 3769 passed vs Windows 3766 passed，差值恰为该 3 个 Linux-only 测试）。
- Full：`python -m pytest` → **3769 passed, 6 skipped, 1 warning in 436.08s**。
- Schema：`python -m research_os.cli.main validate` → **86/86 PASS**。
- Compile：`python -m compileall -q src scripts tests` → **PASS**。

### Provider handling（如实记录）

- GitHub secret `DEEPSEEK_API_KEY`：**未配置**（`gh secret list` 为空）。
- 探针输出 `approved_credential_present: NO`、`connectivity_verified: NOT_VERIFIED`、
  `credential_value_exposed: NO`；未输出 key、未写日志、未写 artifact、未写仓库。
- `FORMAL_ACCEPTANCE_TURN: NO`；probe marker `ENVIRONMENT_READINESS_PROBE_ONLY`。
- 结论：`PROVIDER_BLOCKED`（环境凭证不可用，非实现缺陷；不伪造 READY）。
- 注：approved 凭证在宿主（Windows）环境中存在且 ENV-01 已机械验证
  provider connectivity（一次 bounded probe，191 tokens）；本任务不改动任何
  凭证处理代码。

## Formal trial separation

- `FORMAL_CORPUS_EXECUTED = NO`：本任务不是 P8-B2-LIVE-01，未执行 10 sessions /
  20 turns / acceptance corpus / 股票研究正式任务。
- readiness probe 不是 session、不是 turn，不计入正式 corpus 计数器。
- 探针的 provider-backed 调用标记 `ENVIRONMENT_READINESS_PROBE_ONLY` /
  `FORMAL_ACCEPTANCE_TURN = NO`。

## 状态

- 不记录 `P8-B2 ACCEPTED`；P8-B2 保持 `IMPLEMENTED / PARTIAL / NOT ACCEPTED`。
- **Linux（Ubuntu CI）process validation：PASS**（`PROCESS_CLEANUP_VERIFIED=YES`、
  `PROCESS_RESIDUE=NO`）。
- 整体 readiness：**BLOCKED（provider credential 在 GitHub CI 环境不可用）**。
- Windows 宿主限制（ENV-01）：`PROCESS_CLEANUP_VERIFIED = NOT_VERIFIED`
  （fail-closed），详见 `docs/tasks/p8-b2-env-01-trial-environment-readiness.md`。
