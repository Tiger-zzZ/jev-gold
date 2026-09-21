# jev-gold

**Jev Gold Sentinel** — TypeSafe Jev 作为唯一语义决策核心：读全球冲突/宏观/金价状态，
输出类型化判断，置信度门控后做**纸面**仓位，并留下可复现的校准记录。

研究型 PoC，不是交易策略，不构成投资建议。

## 架构

```
GDELT 日频/15min 脉搏 + FRED + 金价
        → state → Jev 三问（risk / direction / fed_repricing）
        → 门控（conf≥0.8 才动仓）→ SQLite
```

## 快速开始

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # 填 JEV_API_KEY / FRED_API_KEY
python -m jev_gold.loop --once
python -m jev_gold.backtest --resume --out reports
python -m jev_gold.dashboard --out reports/dashboard.html
```

Jev 走 Vercel AI Gateway：`POST https://ai-gateway.vercel.sh/typesafe/v1/systemone`，
模型 `typesafe-ai/jev`。不要用 OpenAI-compatible chat completions。

## 当前状态

- Phase 0–2：真实 Jev + FRED 已通
- Phase 3：事件窗口回测 v1 见 `reports/event_study.md`（样本仍小）
- Phase 4：`python -m jev_gold.dashboard` 生成单文件 HTML；常驻循环按需手动 `--forever`

## 声明

所有决策都是模型实验记录。金价方向难预测；本项目验证的是决策层管线与校准，不是 alpha。
