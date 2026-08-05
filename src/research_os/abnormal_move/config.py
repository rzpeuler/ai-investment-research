"""异动分析配置（Phase 3 任务书 7 节）。

版本号进入幂等键与结构化结果；窗口/阈值/Severity 表为确定性规则，不得由模型决定。
"""
from __future__ import annotations

# ---------- 版本 ----------

ANOMALY_RULES_VERSION = "anomaly.v1"
BENCHMARK_RULES_VERSION = "benchmark.v1"
CAUSE_SCORE_VERSION = "cause.v1"
ATTRIBUTION_RULES_VERSION = "attribution.v1"

# ---------- 数据窗口（任务书 7.1） ----------

BASELINE_WINDOW = 60          # 历史基线窗口（有效交易日）
MIN_ROBUST_BASELINE = 40      # 最低 robust 基线
SHORT_WINDOW = 20             # 短窗口中位数
VOLATILITY_SHORT = 5          # 波动率短窗
VOLATILITY_BASELINE = 60      # 波动率基准窗

MIN_SAMPLE_FULL = 60          # 完整首版指标
MIN_SAMPLE_ROBUST = 40        # 允许 robust 指标（标记样本偏短）
MIN_SAMPLE_LIMITED = 20       # 只计算有限指标
MIN_SAMPLE_NEW_LISTING = 20   # 新股：少于 20 个有效交易日不输出正式分位

BETA_REGRESSION_WINDOW = 60   # Beta 回归窗口
BETA_MIN_SAMPLES = 40         # 回归最低共同有效样本
WINSORIZE_LOW = 0.01          # 1% 分位 Winsorize
WINSORIZE_HIGH = 0.99

MAD_ZERO_FALLBACK_PERCENTILE = "MAD_ZERO_FALLBACK_PERCENTILE"  # MAD=0 回退标志

# ---------- Severity 表（任务书 7.4：双侧分位或绝对 Z，取更严重者） ----------

SEVERITY_TABLE = [
    # (双侧分位下限, 绝对 Z 下限, severity)
    (0.80, 1.28, 1),
    (0.90, 1.65, 2),
    (0.95, 1.96, 3),
    (0.975, 2.24, 4),
    (0.99, 2.58, 5),
]

# ---------- 板块联动（任务书 7.9） ----------

MIN_PEERS_INDUSTRY = 10       # 行业最低同行数
MIN_PEERS_CONCEPT = 8         # 概念最低同行数

# ---------- 个股特异性（任务书 7.10） ----------

IDIOSYNCRATIC_EXCESS_SEVERITY = 4
IDIOSYNCRATIC_CROSS_SECTIONAL_PCT = 97.5
IDIOSYNCRATIC_PEER_MEDIAN_SEVERITY = 1

# ---------- 综合异动成立规则（任务书 7.11） ----------

MOVE_RETURN_SEVERITY = 3      # A 规则：收益/相对收益 severity 门槛
MOVE_VOLUME_SEVERITY = 2      # A 规则：量/额/振幅/波动 severity 门槛
MOVE_ABSOLUTE_SEVERITY = 5    # B 规则：任一主指标 severity=5
MOVE_STATE_SEVERITY = 3       # C 规则：特殊状态下的相对指标门槛
