# jev-gold

**让 Jev 当黄金交易的大脑，代码只做手和账本。**

[Jev](https://typesafe.ai) 是 TypeSafe 的 "System One" 决策模型：它不写文章，只返回类型化的概率判断。这个项目把它接在黄金上——每隔 15 分钟（或每个历史事件窗口），把全球冲突脉搏、宏观利率、金价动量揉成一个 state，问它三个固定的问题，按置信度门控执行**纸面**仓位，并把每次判断连同完整概率分布落库，攒成一份可以事后打分的校准数据集。

研究型 PoC。不是交易策略，不构成投资建议。

## 为什么不用普通 LLM

让大模型写一段"黄金后市分析"很容易，难的是回答：**它说七成的时候，真的有七成对吗？**

自由文本无法校准，错了也无法归因。Jev 的输出是 schema 化的概率（Choice / Score / Noul 三种原语），每次判断都是一行能打分的记录。它**没有世界知识**——只认识你喂进去的 state——所以数据管线就是模型的全部上下文，回测可以严格复现。价格也适合当传感器用：一次三问约 950 input tokens，$0.042/M，15 分钟一拍一天约 $0.04。

## 决策契约（冻结 v1）

一次调用，三个并行问题：

| 问题 | 原语 | 定义 |
|---|---|---|
| `geopolitical_risk` | Score 0–3 | 0=无异常；1=局部紧张但常态；2=明显冲突升级；3=重大系统性冲击 |
| `news_direction` | Choice | bullish_gold / bearish_gold / neutral，各带操作化定义 |
| `fed_repricing` | Noul | 近期新闻是否实质改变了市场对美联储政策路径的预期（0–1） |

门控由代码执行，Jev 无权越过：

- bullish 且 confidence ≥ 0.8 且 risk ≥ 1 → 开多（纸面）
- bearish 且 confidence ≥ 0.8 → 清仓
- 其余 → 不动仓，只记录。**"不行动"也是数据。**

## 架构

```
GDELT 事件文件源（15min/日频，冲突烈度+情绪）─┐
FRED（10Y 实际利率、广义美元指数）            ─┼→ state → Jev 三问 → 置信度门控 → 纸面仓位
yfinance（GLD 日线 / GC=F 期货）              ─┘        │              │
FOMC 声明日历（硬编码 2022–2026）             ─┘   SQLite 全量落库 ←───┘
                                                          │
                                                回测校准 + 单文件仪表盘
```

## Jev 的一次真实判断长什么样

### 2026-09-16，FOMC 三年来首次加息

9 月 16 日 FOMC 加息 25bp 至 3.75–4.00%，2023 年 7 月以来首次，点阵图还暗示年内再加一次。喂给 Jev 的 state：10Y 实际利率 2.62、广义美元 118.2、GLD 收 391.7（此前 5 日已跌 2.9%）、冲突脉搏平稳（冲突事件占比 15.5%）、当天就是声明日。

Jev 的回答：

| 问题 | 答案 | 细节 |
|---|---|---|
| news_direction | **bearish_gold**，conf 0.61 | 概率分布 bear .74 / neutral .21 / bull .05 |
| geopolitical_risk | 1 | 常态区间 |
| fed_repricing | 0.32 | 偏向"政策路径未被实质重定价" |

教科书答案：加息 → 美元强 → 利空黄金。门控：0.61 < 0.8 → **hold，不动仓**。

事后：次日金价 **+1.69%**。鹰派落地即出尽。Jev 的教科书判断短期是错的——而 0.8 的门槛正好挡住了这笔错误操作（5 日标签截至 2026-09-21 尚未到期）。

### 2022-02-24，俄乌全面开战

state：冲突事件占比 19.0%、冲突事件 Goldstein 烈度均值 -7.5、报道语气 -2.7、实际利率 -0.54、GLD 177.1。

Jev：risk=**3**（最高级，"大国间战争爆发或等价冲击"，置信 0.85），bullish_gold conf 0.68（bull 概率 .78）。门控：0.68 < 0.8 → hold，**没有追多**。

事后：次日 -0.33%（避险高开回吐），5 日 +2.07%。方向对、节奏错——置信度没过线，账面躲过次日回撤。

### 门控的代价也如实记录

2026-07-29 FOMC 按兵不动（三名委员异议、主张加息），Jev 给 neutral，conf 只有 0.20（neutral .47 / bear .37 / bull .16）——它说"看不清"。之后 5 日金价 +5.0%，这段涨幅被错过。门槛既挡错也挡对，这正是需要持续攒校准数据的原因。

## 22 个事件窗口的完整记录

2022-02 至 2026-09，每个窗口至多一次 Jev 调用，标签为随后 1/5 个交易日 GLD 收益。Jev 只看到事件日当天的 state。

| 日期 | 类型 | 方向 (conf) | risk | 门控 | 次日 % | 1d | 5d |
|---|---|---|---|---|---|---|---|
| 2022-02-24 俄乌开战 | geo | bullish (0.68) | 3 | hold | -0.33 | miss | hit |
| 2022-03-16 首次加息 | fomc | bearish (0.28) | 2 | hold | +0.49 | miss | miss |
| 2022-06-15 +75bp | fomc | bearish (0.71) | 1 | hold | +1.12 | miss | hit |
| 2022-09-26 北溪 | geo | neutral (0.15) | 2 | hold | +0.21 | – | – |
| 2023-03-10 SVB | geo | bullish (0.22) | 1 | hold | +2.30 | hit | hit |
| 2023-03-22 FOMC | fomc | neutral (0.30) | 1 | hold | +1.25 | – | – |
| 2023-07-12 平静期 | ctrl | neutral (0.39) | 1 | hold | +0.07 | – | – |
| 2023-10-07 哈马斯 | geo | bullish (0.62) | 2 | hold | -0.17 | miss | hit |
| 2024-04-13 伊朗-以色列 | geo | bullish (0.32) | 2 | hold | +0.12 | miss | miss |
| 2024-09-18 -50bp | fomc | bullish (0.49) | 1 | hold | +1.55 | hit | hit |
| 2024-11-07 -25bp | fomc | neutral (0.13) | 1 | hold | -0.68 | – | – |
| 2024-12-18 -25bp | fomc | neutral (0.07) | 1 | hold | +0.14 | – | – |
| 2025-05-07 维持 | fomc | neutral (0.44) | 1 | hold | -1.97 | – | – |
| 2025-08-15 平静期 | ctrl | neutral (0.40) | 1 | hold | -0.16 | – | – |
| 2025-09-17 -25bp | fomc | bullish (0.23) | 1 | hold | -0.40 | miss | hit |
| 2025-10-29 -25bp | fomc | neutral (0.12) | 1 | hold | +1.96 | – | – |
| 2025-12-10 -25bp | fomc | neutral (0.22) | 1 | hold | +1.08 | – | – |
| 2026-01-28 维持 | fomc | neutral (0.20) | 1 | hold | +0.27 | – | – |
| 2026-03-18 维持+SEP | fomc | neutral (0.21) | 1 | hold | -4.12 | – | – |
| 2026-06-17 维持+SEP | fomc | neutral (0.28) | 1 | hold | -0.38 | – | – |
| 2026-07-29 维持(3票异议) | fomc | neutral (0.20) | 1 | hold | +1.64 | – | – |
| 2026-09-16 +25bp | fomc | bearish (0.61) | 1 | hold | +1.69 | miss | 未到期 |

汇总（排除 neutral 与未到期标签）：

| 指标 | 值 |
|---|---|
| 1d 方向命中 | 2/9 = 22% |
| 5d 方向命中 | 6/8 = 75% |
| 开仓次数 | 0 |
| ≥0.80 置信度样本 | 0 |

置信度分桶（1d 方向判断）：

| bucket | n | hits |
|---|---|---|
| 0.00–0.40 | 4 | 1 |
| 0.40–0.60 | 1 | 1 |
| 0.60–0.80 | 4 | 0 |
| 0.80–1.00 | 0 | 0 |

这些数字该怎么读（诚实版）：

- n 太小，22% / 75% 都不构成结论，只是观察记录。
- **≥0.80 的置信度至今一次没出现过**，即使在俄乌开战当天（0.68）。v1 门控因此从未开仓，策略净值约等于现金。
- 0.60–0.80 桶 4 次方向判断次日全 miss。如果这组样本有指示性，指示的方向是"置信度不到就别动"。
- 本项目验证的是**决策管线 + 校准方法**，不是金价预测能力。金价方向本身极难预测。

## 数据源

| 源 | 用途 | 备注 |
|---|---|---|
| GDELT v2 事件文件源 | 冲突脉搏：事件数、冲突占比、Goldstein 烈度、AvgTone | 15min/日频 zip，免 key，同格式回溯 2015；DOC API 限流极严，只作头条辅路 |
| FRED | DFII10（10Y 实际利率）、DTWEXBGS（广义美元） | 免费 key，日频 |
| yfinance | GLD 日线（回测标签）、GC=F（实时） | 免费，无需 key |
| FOMC 声明日历 | state 中的"距下次 FOMC 天数" | 硬编码 2022–2026 |

## 复现

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env      # 填 JEV_API_KEY（Vercel AI Gateway）和 FRED_API_KEY
python -m jev_gold.loop --once        # 单拍：取数 → Jev → 门控 → 落库
python -m jev_gold.backtest --resume  # 22 窗事件回测；--resume 复用已有结果，不重复烧 token
python -m jev_gold.dashboard          # 生成 reports/dashboard.html
python -m unittest discover -s tests  # 26 项单测，不打真实 API
```

Jev 走 Vercel AI Gateway：`POST https://ai-gateway.vercel.sh/typesafe/v1/systemone`，模型 `typesafe-ai/jev`（注意：不是 OpenAI 兼容的 chat completions）。没有 key 时设 `JEV_GOLD_JUDGE=mock`，用确定性占位判断器联调管线。`reports/` 不入库，上表用 `--resume` 可原样复现。

## 边界

- Jev 无世界知识，它只认识 state 里的数字和头条——数据管线即上下文，喂错数据它会自信地给错答案。
- 纯纸面交易，v1 不做空。所有记录都是模型实验数据，不构成投资建议。
