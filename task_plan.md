# Jev Gold Sentinel — 任务计划

> 用 TypeSafe Jev（System One 决策模型）作为**唯一决策核心**，读取全球新闻/冲突/宏观数据，
> 对黄金做出类型化判断，置信度门控后执行纸面交易，并产出**公开校准数据集**。
> 定位：研究型 PoC + 校准实测，**不是**盈利策略、不构成投资建议。

## 核心原则

1. **Jev 是唯一判断者**：所有语义判断（地缘风险、新闻方向、美联储预期）只能由 Jev 产出；
   代码只负责取数、组装 state、执行门控规则、记账。绝不写"代码自己猜方向"的逻辑。
2. **先回测后实时**：先用历史数据验证管线和校准性，再开实时循环。
3. **置信度门控是一等公民**：高置信才动仓，低置信只记录；"不行动"也是数据。
4. **KISS**：15 分钟一拍、单进程、SQLite 存储，够用即可。

## 架构

```
GDELT (15min, 冲突/情绪/头条)  ─┐
FRED  (daily, 实际利率/美元)    ─┼→ [state 组装] → [Jev 三问] → [置信度门控] → [纸面仓位/记账]
yfinance (GC=F / GLD 价格)     ─┘        │              │              │
FOMC 日历 (硬编码)             ─┘        ▼              ▼              ▼
                                      SQLite ←──── 决策日志（含概率/置信度）────┘
                                                │
                                                ▼
                                     回测校准分析 + 仪表盘
```

## Jev 决策契约（项目的心脏，改动需评审）

一次调用，三个并行问题（初版）：

| 问题 | 原语 | 定义 |
|---|---|---|
| `geopolitical_risk` | Score | 0=无异常；1=局部紧张但常态；2=明显冲突升级；3=重大系统性冲击 |
| `news_direction` | Choice | bullish_gold / bearish_gold / neutral（各带 criteria 描述） |
| `fed_repricing` | Noul | "近期新闻是否实质改变了市场对美联储政策路径的预期？" |

门控规则（初版，可调）：
- `news_direction` confidence ≥ 0.8 且 `geopolitical_risk` ≥ 1 → 允许调整纸面仓位（long/flat，v1 不做空）
- 其余情况 → 不动仓，仅记录
- 每次决策全量落库：state 快照、三问返回的完整概率分布、门控结果

## 阶段与任务

### Phase 0 — 访问与验证 ✅（2026-09-21 真实 Jev 通过）
- [x] **（用户操作）** Vercel AI Gateway 开通并绑支付 → 模型 ID `typesafe-ai/jev`
- [x] **（用户操作）** FRED API key 已接入并验证（DFII10=2.61，DTWEXBGS=118.21）
- [x] 验证 GDELT 端点可用性（文件源为主；DOC API 限流严重，仅作头条辅路）
- [x] 核对 Jev HTTP 契约：`POST https://ai-gateway.vercel.sh/typesafe/v1/systemone`
- [x] Jev smoke test（隔离调用 + 全链路 `--once` 均通过）

### Phase 1 — 数据链路 ✅（2026-09-20 完成，冒烟通过）
- [x] `ingest/gdelt.py`：文件源聚合冲突脉搏（events/conflict_share/Goldstein/AvgTone）+ DOC API 头条
- [x] `ingest/fred.py`：DFII10 + DTWEXBGS，无 key 降级 None
- [x] `ingest/price.py`：GC=F 小时线，回退 GLD 日线
- [x] `db.py`：SQLite 四表（snapshots/decisions/positions/prices）
- [x] FOMC 日历硬编码（state.py，标注待核对）

### Phase 2 — 决策核心 ✅（2026-09-21 真实 Jev 接入）
- [x] `state.py`：state 组装器（脉搏/头条/宏观/价格/事件日历）
- [x] `judge.py`：MockJudge + JevJudge（Gateway TypeSafe 兼容端点）
- [x] `gate.py`：置信度门控 v1
- [x] 决策日志 v1 落库（完整概率分布 + 门控理由）
- [x] 真实链路 smoke：judge=jev，data_ok=True，answers 含三问分布

### Phase 3 — 回测与校准（v2，20 窗口全部 jev_ok，2026-09-21）
- [x] 事件窗口回测：20 个窗口 × 至多 1 次 Jev；`--resume` 跳过已成功
- [x] GDELT 日频 zip 本地缓存 `.cache/gdelt/`
- [x] 报告：`reports/event_study.md/.csv/.json`（含 1d/5d 命中 + 置信度分桶）
- [x] 校准分桶已出（n 仍小：方向判断 8 条，≥0.80 桶为 0）
- [ ] 样本仍不足以当校准曲线发布；≥0.80 桶尚无观测

### Phase 4 — 实时循环与仪表盘
- [x] `--forever` 已实现；曾在本机启动，后因内存被系统杀掉（2026-09-21），暂不自动重启
- [x] 单文件 HTML 仪表盘：`python -m jev_gold.dashboard` → `reports/dashboard.html`
- [x] 纸面 NAV vs buy&hold（v1 全 hold，策略近似现金）

### Phase 5 — 发布
- [x] README 已更新（架构、复现、免责声明）
- [ ] 校准数据集公开（建议等 ≥0.80 桶有样本再发）
- [ ] 发布渠道：GitHub + 掘金/知乎（中文圈）+ X（英文圈）

## 关键决策（已定）

| 决策 | 选择 | 理由 |
|---|---|---|
| 标的 | 黄金（GLD/GC=F） | 三方案对比：演示效果+数据链完整性双优；生态空白 |
| 栈 | Python | 数据处理/回测生态最强；有官方 typesafe-sdk-python |
| 决策频率 | 15 分钟 | 匹配 GDELT 更新节奏；日成本 ~$0.04，可忽略 |
| 执行 | 纯纸面交易 | PoC 定位，规避合规与资金风险 |
| v1 不做空 | 只 long/flat | 简化记账；门控规则更直观 |
| 冲突信号源 | GDELT（不用 Twitter/X） | 免费、免 key、15min 更新、历史到 2015、自带冲突分级与情绪分 |

## 待决问题

- [x] ~~Jev 访问路径~~ → **Vercel AI Gateway**（用户确认 2026-09-20）
- [x] ~~开工节奏~~ → **先建管线**，mock judge 占位，拿到 key 一行切换（用户确认 2026-09-20）
- [ ] 仓库是否建 GitHub 公开 repo（建议：Phase 3 出结果前私有，发布时转公开）
- [x] ~~仪表盘形态~~ → 单文件 HTML（`reports/dashboard.html`）

## 成功标准

1. 管线端到端跑通：数据 → Jev → 门控 → 记账，无人值守 2 周不出错
2. 产出一份可复现的校准报告（含校准曲线 + 至少 20 个历史事件窗口）
3. README 能让别人 30 分钟内复现管线
