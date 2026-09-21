# 进度日志

## 2026-09-20 — 项目立项

**完成：**
- Tavily 调研 Jev 全貌（是什么/生态/场景适配/竞品类项目拆解）
- 三方案对比（Henry Hub / A股 / 黄金）→ 选定黄金
- 创建项目规划根 `/Users/anno/flyfly/jev-gold/`（task_plan.md / findings.md / progress.md）
- 冻结 Jev 决策契约 v1（geopolitical_risk / news_direction / fed_repricing）与门控规则 v1

**进行中（更新 1）：**
- 用户确认：Jev 走 Vercel AI Gateway；先建管线（mock judge 占位）
- Phase 1/2 代码骨架完成：config / db(SQLite×4表) / ingest(gdelt·fred·price) / state / judge(mock+jev) / gate / loop
- 冒烟测试 1：yfinance ✅（GC=F 4424.9）、mock judge ✅、熔断 ✅；GDELT 429 ❌ → 已加 UA+退避重试

**进行中（更新 2）：**
- ✅ **端到端冒烟通过**（03:56 UTC）：文件源脉搏(events=444, conflict_share=0.2275) + GC=F 价格 + mock judge + 门控 + SQLite 落库，全链路 data_ok=True
- GDELT DOC API 限流远超文档（小时级冷却）→ 冲突脉搏改走文件源（带 15min 步长回退，解决 lastupdate.txt 提前引用 404 的坑）
- Phase 1 ✅ 完成；Phase 2 代码完成，仅剩真实 Jev 接入

**下一步：**
- 用户开通 Vercel AI Gateway（typesafe-ai/jev）+ 可选 FRED key
- 拿到 key：核对 judge.py 的 HTTP 契约 TODO → 真实链路 smoke → 开常驻循环积累数据
- 之后进入 Phase 3 回测（文件源同格式历史到 2015，解析器直接复用）

## 2026-09-21 — 真实 Jev 接入

**完成：**
- Key 写入 gitignored `.env`（不入库、不回显）
- 核对 Vercel TypeSafe 兼容契约：`POST https://ai-gateway.vercel.sh/typesafe/v1/systemone`，模型 `typesafe-ai/jev`
- 隔离 smoke：risk=1 / direction=neutral / fed_repricing=0.17，usage 726/81 tokens
- 全链路 `--once`：judge=jev, data_ok=True；GC=F 4412.0；conflict_share=0.1854；direction=bullish_gold(conf=0.53) → 门控 hold
- DOC 头条 429 不再长退避，失败即降级以免卡住 15min 节拍
- Phase 0 / Phase 2 真实链路关闭

**进行中：**
- 启动 `--forever` 15min 常驻循环积累决策日志

**下一步：**
- 可选 FRED key（macro 仍可空跑）
- Phase 3 回测/校准（文件源历史格式已对齐）
- 仪表盘仍待决（终端先行 vs web）

## 2026-09-21 — FRED + 事件窗口回测

**完成：**
- FRED key 写入 `.env` 并验证：DFII10=2.61，DTWEXBGS=118.21
- 修 `.env` 空值覆盖（setdefault 不会覆盖空字符串）
- FOMC 日历补到 2024–2026 声明日
- `backtest.py`：12 事件窗口，GDELT 脉搏缺失则跳过 Jev（避免污染校准）
- 日频 GDELT zip：https 截断 → 流式下载 + http 回退；2024-09-18 实测 143,615 事件
- 报告：`reports/event_study.{md,csv,json}`
- JevJudge 增加 3 次重试（SSL 抖动）

**回测要点（非盈利结论）：**
- 12 窗口中 8 次真实 Jev、4 次 GDELT 下载失败跳过
- 门控全部 hold（最高 direction conf=0.65，阈值 0.8）
- 地缘 3 窗：risk=2–3、方向偏 bullish，次日金价小幅下跌或接近 0 → 1d 方向 miss
- FOMC 降息窗 2024-09-18：bullish + 次日 +1.55% → hit
- 近年 FOMC hold 窗多为低置信 neutral

**未做：**
- 常驻循环被系统因内存杀掉，未重启（避免再占内存）
- 校准曲线样本不够

## 2026-09-21 — 扩大事件集 + 仪表盘

**完成：**
- FOMC 日历补 2022–2023，避免历史窗 `days_to_next_fomc` 错位
- GDELT 日频 zip 缓存到 `.cache/gdelt/`
- 事件集扩到 20 窗；`--resume` 只补失败/新窗
- 20/20 `jev_ok`；先前 4 个下载失败窗全部补上
- 仪表盘：`reports/dashboard.html`
- README 同步到当前状态

**v2 回测（非盈利）：**
- 1d 方向命中 2/8=25%；5d 6/8=75%（地缘窗次日回吐、5 日同向更常见）
- 全部 gate=hold；≥0.80 桶仍为 0
- 加息窗 2022-06 bearish(0.71) 次日金价反涨 → 高置信仍可错

**未做：**
- 不重启 `--forever`（内存）
- 不把 25%/75% 当校准结论对外发布
