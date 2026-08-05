# Schema 与 Python 数据模型契约说明

**适用范围**：`schemas/*.schema.json`（权威 JSON Schema）与 `src/research_os/models/core.py`（Pydantic 模型）。
**版本**：Phase 0.1 固化。

## 1. 角色划分

| 层 | 角色 |
| --- | --- |
| JSON Schema | **完整对象规范**。持久化、模块间传输、外部接口的唯一权威契约。 |
| Pydantic 模型 | 对象**构造器**。提供默认值、类型校验与构造便利，是 Schema 的实现细节。 |

## 2. 明确规则

1. **JSON Schema 表示完整对象规范**：Schema 中全部字段保持 `required`（含带默认值的字段）。
   任何"完整对象"（落库、模块调用、外部接口输出）都必须包含全部字段。
2. **Pydantic 默认值仅用于构造便利**：模型允许省略带默认值的字段，构造后自动填充。
   这**不是** Schema 的放宽——Schema 的 `required` 语义不变。
3. **必须完整 dump 后才能流转**：Pydantic 对象在进入持久化、模块调用或外部接口前，
   必须执行 `model_dump()` 生成完整 dict。
4. **dump 后必须通过 JSON Schema**：`model_dump()` 的结果必须通过对应
   `schemas/*.schema.json` 校验（`validators/schema_validator.validate_instance`）。
   测试 `tests/unit/test_model_contract.py` 对 9 个核心对象持续验证此规则。
5. **禁止裸模型局部字段流转**：禁止将未 dump 的模型局部字段（如 `task.status` 单独取值）
   直接写入数据库或模块间传递。所有持久化/传输一律使用完整 dump 对象。
6. **裸 dict 输入从严校验**：外部传入的裸 dict（LLM 输出、采集器结果、用户输入）
   按 JSON Schema 的严格规则验证（含 `additionalProperties: false`），不享受模型默认值。

## 3. 一致性说明（审计确认）

- 字段集合：模型与 Schema 完全一致（无多无少）。
- 枚举值：模型 Literal 与 Schema enum 完全一致。
- 默认值：模型默认值与 Schema default 一致。
- **必填语义差异（已知且有意的）**：Schema 全量 `required`；模型对带默认值字段允许省略。
  运行时已验证：任意合法模型 `model_dump()` 100% 通过 Schema 校验，无破坏。
  此差异不通过放宽 Schema 消除，而是通过"模型只负责构造、Schema 负责校验"的职责分离解决。

## 4. 示例验证

```python
task = Task(scenario="morning_brief", requested_at="2026-08-05T08:00:00",
            as_of="2026-08-05T08:00:00")          # 最小构造（省略带默认值字段）
full = task.model_dump()                           # 完整 dump（默认值已填充）
errors = validate_instance(full, "task")           # Schema 严格校验
assert errors == []
```
