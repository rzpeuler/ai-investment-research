# P8-ARCH-001 — Harness Hybrid Runtime Architecture Freeze

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE (Sol)

Task: P8-ARCH-001-HARNESS-HYBRID-RUNTIME-ARCHITECTURE-FREEZE
（治理冻结任务：只改文档，不实现代码）

## 1. 目标

将 DeepSeek Harness Hybrid Runtime Architecture 正式写入项目治理文档，冻结
未来系统边界，避免后续开发将 Harness 误解为 Research OS 全量替代 Runtime。

## 2. 背景

P8-B2 阶段实际验证：Harness 不适合作为默认严格结构化研究生成 Runtime
（benchmark：Harness schema_valid_rate = 0.10，Legacy = 0.90，P8-B3 门槛
0.70 NOT_MET）。因此架构调整为 Hybrid Agent Runtime Architecture：Harness
= Agent Orchestration Runtime（会话 / 目标 / Skill / Tool / 探索），Research
OS = Research Intelligence Authority（身份 / 就绪 / 采集 / 证据 / PIT / 图谱 /
工作流 / Validator / 报告）。

## 3. 范围

### 允许

- docs/project-state/DECISIONS.md
- docs/engineering-guide.md
- docs/architecture/*
- CURRENT_STATE.md
- NEXT_PHASE.md
- KNOWN_LIMITATIONS.md

### 禁止

- Harness 代码接入
- MCP 实现
- Skill 实现
- Runtime 切换
- 修改 D4 范围

## 4. 完成内容

### 4.1 新增 Architecture Decision

`docs/project-state/DECISIONS.md` **Decision #80**：Harness Hybrid Runtime
Architecture Freeze。包含：Harness 定位、Research OS 定位、Skill/Tool 边界、
MCP 边界、Memory 边界。

### 4.2 新增 Agent Runtime Architecture 文档

`docs/architecture/harness-hybrid-runtime-architecture.md`：
Hybrid Runtime Architecture（DESIGN FROZEN / NOT IMPLEMENTED）。并在既有
`docs/architecture/agent-runtime-skill-architecture.md`（Decision #54）顶部
补充指向与继承声明，避免矛盾。

### 4.3 更新 CURRENT_STATE

状态块增加：

```text
HARNESS_ARCHITECTURE: DESIGN_FROZEN
HARNESS_IMPLEMENTATION: NOT_IMPLEMENTED
PRODUCTION_ACCEPTANCE: NO
```

### 4.4 更新 NEXT_PHASE

明确：D4 完成后进入 P8-A0 Hybrid Agent Runtime Spike。

### 4.5 更新 KNOWN_LIMITATIONS

记录：当前 Session 仍未迁移到 Harness（P7-UX1 IN_MEMORY_ONLY）。

### 4.6 更新 engineering-guide

§0.8 补充 Hybrid 运行时边界原则（Harness 不作为默认严格结构化生成 runtime）。

## 5. 验收

- 文档一致性：无矛盾架构描述（#54 与 #80 边界继承一致）；
- 无提前宣布生产采用（HARNESS_IMPLEMENTATION=NOT_IMPLEMENTED、
  PRODUCTION_ACCEPTANCE=NO）；
- D4 范围不改变。

## 6. 测试 / 检查

- 文档交叉引用检查：新增文档引用的路径 / Decision 编号存在；
- git diff 检查：production code 0 changes；
- 无代码测试（纯文档治理任务）。

## 7. 状态

- P8-ARCH-001 为治理冻结任务；Agent 不得 self-accept。
- Harness 生产采用保持 NOT_AUTHORIZED；默认 runtime 保持 legacy。
