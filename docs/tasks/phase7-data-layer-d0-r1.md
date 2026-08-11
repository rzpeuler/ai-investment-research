# P7-D0-R1：Contract Strictness & Governance Closure

**TASKBOOK_STATUS: IMPLEMENTATION AUTHORIZED — R1 REPAIR ONLY**
**MILESTONE: P7-D0-R1**
**START_HEAD: `10489041efbc8e7dc5507fb48101230996b67535`**
**P7-D1: NOT AUTHORIZED**
**NEW COLLECTORS: NO**
**SOURCE EXPANSION: NO**
**NETWORK ACQUISITION: NO**
**GRAPH WRITE: NONE**
**PHASE6.1: NOT AUTHORIZED**
**DB: v6**
**MIGRATIONS: NONE**
**SCHEMA_COUNT: 85 — MUST REMAIN 85**

> P7-D0 independent acceptance: CHANGES_REQUIRED
> R1 scope: contract strictness + governance closure（3 个阻塞问题 + 2 个治理收口）
> 本任务不是重新实现 P7-D0，只修独立验收发现的问题。

## 1. R1-01 BriefAttentionSnapshot.public_metrics 彻底 strict

原 `public_metrics` 为 `additionalProperties: true` 的自由键 object，形成契约旁路
（可塞 trend / historical_heat / velocity / rank_change）。改为：

```text
public_metrics: array[PublicMetric]
```

`PublicMetric` 是 `brief_attention_snapshot.schema.json` 内部 nested strict object
（不新增第 86 个顶层 Schema）：

```text
type: object
additionalProperties: false
required: [metric_name, value, unit, source_reference, observed_at]

metric_name:      string / minLength 1
value:            number | integer | string | null
unit:             string | null
source_reference: string | null
observed_at:      date-time | null
```

Pydantic 新增 `PublicMetric` 构造模型；`AttentionTopic.public_metrics` 从 `dict` 改为
`List[PublicMetric]`，默认 `[]`。value 只保存平台公开观察值，不得编码趋势/变化类字段。

## 2. R1-02 ScenarioDataRequirement.scope 完整对象 required

`scope.required` 补全为：

```text
scope_type
reference
watchlist_group
```

`reference` / `watchlist_group` 为 `string | null`；Pydantic 保持 `Optional[str] = None`，
`RequirementScope(scope_type="global")` dump 后三字段全存在并通过 Schema。

## 3. R1-03 Scenario Registry 真正 fail-closed

解析 `scenarios` 后立即计算 `actual = set(scenarios.keys())` 与
`expected = set(SCENARIO_IDS)`：

```text
missing 非空 → REJECT（缺少 Scenario: [...]）
unknown 非空 → REJECT（未知 Scenario: [...]）
```

scenario wrapper 只允许 `description` / `requirements`，出现 `source` / `provider` /
`foo` / `runtime_config` 等未知字段必须拒绝。修复原假阳性测试
`test_unknown_scenario_rejected`：拆分为「完整 10 场景 + unknown_11th → FAIL」与
「缺一个合法场景 → FAIL」两个独立测试。

## 4. R1-04 FAST_NEWS 从 C watchlist 机器边界排除

`brief_watchlist.yaml` 增加机器可读 `content_scope`（watchlist registry 字段，非新
业务 Schema）：

```text
all_public_content
non_fast_news_only
public_institution_material
```

财联社 C 条目改为：

```yaml
name: 财联社（非7×24快讯内容）
content_scope: non_fast_news_only
notes: Requirement C 仅覆盖财联社非 7×24 快讯的财经媒体内容；7×24 快讯由 Requirement A / news_flash 处理
```

其他普通财经/行业/社区项目 `content_scope: all_public_content`；机构类
`public_institution_material`。Loader 用 Literal/enum 拒绝非法值；所有完整 entry
显式写该字段。不删除财联社渠道，只排除 7×24 快讯流。

## 5. R1-05 last_verified_at 不得伪装联网验证

正式冻结 `last_verified_at` 含义：对该具体 watch entry 的访问/身份/来源可用性进行过
真实验证的最近时间。本阶段未做任何验证，所有条目：

```yaml
last_verified_at: null
```

Pydantic `Optional[str] = None`；非 null 时必须 `validate_iso()`，非法 ISO 拒绝。
不得为了验证 25 个名单去联网。

## 6. R1-06 Router 治理措辞收口

Decision #47 §47.5 与工程指南 V1.5 同步收口（不升级 V1.6）：

```text
SECOND_ROUTER: NO
P7_D0_ROUTER_EVOLUTION: NONE
EXISTING_ROUTER_FUTURE_EVOLUTION: ONLY UNDER SEPARATE MILESTONE AUTHORIZATION
```

正文明确：P7-D0 禁止实现 Router v2 或修改现有 Router 核心语义；未来 P7-D1 或后续经
独立授权后可以演化现有 Router，但不得创建并行的第二套路由控制面。禁止修改
`src/research_os/routing/router.py`。

## 7. 完成定义

```text
public_metrics 不是自由 dict
所有 nested object additionalProperties=false
scope 完整字段全部 required
第 11 个 scenario fail-closed
missing scenario fail-closed
wrapper unknown field fail-closed
财联社 C 机器边界排除 7×24 快讯
FAST_NEWS 仍只属于 A
未验证 watchlist last_verified_at=null
Router 措辞不再永久禁止现有 Router 演化
Schema 仍 85 / Scenario 10/10 / Requirements 43
DB v6 / migration none / collectors 0 / source registry unchanged
router core unchanged / brief pipeline unchanged / LLM calls 0
Graph write none / Phase6.1 not authorized / P7-D1 not authorized
pytest 0 failed / 85/85 Schema PASS / compileall PASS / diff check PASS
PR #24 仍 OPEN / NOT MERGED
```

完成后只能报告：

```text
P7-D0-R1: IMPLEMENTED / AWAITING INDEPENDENT RE-ACCEPTANCE
```

不得自行声明 PASS。
