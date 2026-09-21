# 调研发现（2026-09-20，Tavily 调研）

## Jev 关键事实

- TypeSafe AI（Diogo Almeida 等创立，$40M 种子轮）2026-09-15 发布；"System One model"：只返回类型化概率决策，不生成文本
- 三原语：**Choice**（≤255 选项+各项概率+confidence）、**Noul**（命题为真的概率 0~1，≈0.5=不确定）、**Score**（有序量表，每级需操作化定义）
- 训练方法 RLCD：优化"认知诚实的概率"（校准=群体属性：说 90% 应约 90% 对；不保证单次正确）
- 性能/价格：延迟 70–500ms（官方称多数 ~100ms）；$0.042/百万 input token，输出免费；约 $0.0004/决策
- 请求预算 ~32k token；一次请求多问题并行且相互独立
- **边界**：无世界知识（只认识传入的 state）；不会产出 schema 外值但会"自信地选错"；官方 benchmark 是与 GPT-6 Astra/Fable 5.1 的一致率而非独立标注
- 接入：官方 API（waitlist）或 Vercel AI Gateway（`typesafe-ai/jev`，同价，跳过 waitlist）；官方 Python/JS SDK 在 github.com/typesafe-ai
- **Gateway 实测（2026-09-21）**：不走 OpenAI-compatible chat completions。正确端点 `POST https://ai-gateway.vercel.sh/typesafe/v1/systemone`，Bearer `vck_…`。问题类型仍是 `noul/choice/score`（AI SDK 里的 `boolean` 是别名）。Score 用 `criteria` 数组，返回浮点 `score` + 分桶 `probabilities`。实测一次三问约 700–850 input tokens。偶发 SSL EOF，客户端需重试。
- **FRED 实测**：DFII10（10Y 实际利率）2.61；DTWEXBGS（广义美元）118.21。
- **事件窗口 v2（20/20 jev_ok）**：1d 方向命中 2/8=25%，5d 6/8=75%。地缘窗常见「次日回吐、5 日同向」。v1 阈值 0.8 仍从未开仓；0.60–0.80 桶 3 条全 miss。加息窗 2022-06 bearish(0.71) 次日金价反涨。支持决策层+门控，不支持把 Jev 当金价预测器。

## 数据源清单（全部免费，已验证）

| 源 | 内容 | 频率 | 历史 | 备注 |
|---|---|---|---|---|
| GDELT 2.0 Event DB / GKG | 全球冲突事件（GoldsteinScale 烈度）、情绪（AvgTone） | 15min | 2015+ | 免 key，65 语种机器翻译 |
| GDELT DOC 2.0 API | 关键词头条、报道量时间线（TimelineVol） | 15min | 近 3 个月查询 | 英文关键词可跨语种搜 |

**GDELT 实测教训（2026-09-20）**：名义限流 5s/次，实际严格得多——连续请求会触发 IP 级冷却，
需要 ~60-120s 完全静默才恢复；每次冷却期内的请求可能延长封禁。与 UA、查询复杂度无关（已对照实验）。
artlist 已实测结构：`{"articles":[{url,title,seendate,domain,language,sourcecountry}]}`；
非英文查询会返回当地语言文章（gold 查询匹配到印尼语），已用 `sourcelang:english` 限定。

**最终架构（已落地并冒烟通过）**：冲突脉搏走 **GDELT v2 文件源**（data.gdeltproject.org，
与 API 限流隔离，15min 一个 ~40KB Events zip，直接含 GoldsteinScale/AvgTone，历史同格式回溯 2015）。
DOC API 仅用于非关键的黄金头条。文件源陷阱：lastupdate.txt 会**提前引用尚未生成的文件**
（03:55 列出 040000 但 404）→ 客户端按 15min 步长回退 2 个间隔取最新可用文件（已实现）。
冒烟实测值：15min 全球 444 事件、冲突占比 22.75%、冲突事件 Goldstein 均值 -8.155、平均语气 -1.952。
TSV 列索引：28=EventRootCode, 29=QuadClass, 30=GoldsteinScale, 31=NumMentions, 34=AvgTone。
| FRED | DFII10（10Y 实际利率）等 | 日 | 数十年 | 免费 key |
| yfinance | GC=F 期货 / GLD ETF | 准实时(延迟) | 数十年 | PoC 足够 |
| FOMC/CPI 日历 | 固定日期 | 8+12 次/年 | 全 | 硬编码即可 |

## 竞品与生态

- jarrodwatts/jev-trader（Monad 员工出品，X 110 万浏览）：每 300ms 区块问 Jev buy/sell，挂单边限价单。
  **本质是工程演示非 alpha**：state 只有盘口数字（Jev 无世界知识的最弱用法）；
  严肃化需 OFI/VPIN/Avellaneda-Stoikov/对冲，Jev 只占一个方向判断位
- 生态里**无人做黄金/大宗商品**（仅有同类链上 bot 仿品 zadescoxp/Jev-Trades）→ 空白
- 生态最缺：独立校准评测（官方未公开校准曲线，Substack/Latent.Space 均点名）→ 本项目的差异化交付

## 三方案对比结论（详见对话记录）

黄金 ★★★（数据链完整+演示效果+最简单）> Henry Hub ★★☆（因果最干净但周频平淡，彭博付费墙/管道公告难抓）> A股 ★★☆（归因噪声大+荐股合规红线）

## 风险与边界

- 金价方向可预测性低（实际利率/央行购金多因子）→ 项目价值在"管线+校准数据"，不在方向准确率
- GDELT 情绪分噪声大，需做平滑/基线对比
- 所有输出必须带免责声明；不做实盘接口
- Jev 厂商风险：定价可能补贴、waitlist 政策、RLCD 细节未公开
