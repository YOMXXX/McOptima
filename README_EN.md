# McOptima - McDonald's Menu Optimizer 🍔

> Exhaustively search the McDonald's China menu with operations research to find the **global optimum** for your appetite.
>
> Satisfaction maximization under budget · Calorie-capped substitutes · Protein floors · Best-value combos — a multi-constraint 0/1 knapsack solver powered by McDonald's official MCP real-time data.

[![CI](https://img.shields.io/badge/CI-passing-brightgreen)](#) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](#) [![MCP](https://img.shields.io/badge/Powered%20by-McDonald's%20MCP-red)](#)

**Entry for the 2026 McDonald's China Programmer Innovation Challenge** (not an official McDonald's product). Menu data currently covers mainland China stores (in Chinese).

---

## Why?

The McDonald's App **promotes** to you. It doesn't **optimize** for you.

| | App's suggestions | McOptima's solution |
|---|---|---|
| Stance | Maximize platform revenue | **Maximize YOUR satisfaction** |
| Logic | What inventory to clear today | Global optimum under budget × calorie × protein constraints |
| Result | "Add a pie for just ¥5?" | "¥30 budget buys 713kcal / 45g protein, ¥0.1 left" |

## Core capability

```
maximize   Σ satisfactionᵢ · xᵢ
subject to Σ priceᵢ · xᵢ ≤ your budget
           Σ kcalᵢ · xᵢ ≤ your calorie cap
           Σ proteinᵢ · xᵢ ≥ your protein floor
           Σ sodiumᵢ · xᵢ ≤ your sodium cap (optional)
```

- 🥇 **Feast mode**: "Only ¥30, want to eat well" → top-3 combos
- 💪 **Muscle mode**: "Need 30g protein after leg day" → protein-density ranked optimum
- 🔁 **Substitute**: "Craving a Big Mac meal but under 600kcal" → similar-satisfaction, lower-kcal alternatives
- 🌙 **Late-night supply**: caffeine-aware post-22:00 planning
- 👥 **Group ordering**: team meal planning (beType=6 enterprise scenario)

All data comes from McDonald's official MCP (menu / prices / nutrition / coupons). Final prices verified via `calculate-price` in real time.

## Quick start

### CLI

```bash
export MCD_MCP_TOKEN=your_token   # apply at open.mcd.cn/mcp
cd skill/scripts
python3 cli.py 1450713 --mode feast --budget 30
# or resolve store by city + landmark:
python3 cli.py "上海市 人民广场" --mode muscle --budget 40 --protein 35
```

### WorkBuddy Skill

1. Apply for an MCP Token at [open.mcd.cn/mcp](https://open.mcd.cn/mcp)
2. WorkBuddy → sidebar 【专家·技能·连接器】→【连接器】→【自定义连接器】→【配置MCP】
3. Paste the config from `mcp-config.example.json` (replace YOUR_MCP_TOKEN), enable the connector
4. Drop the `skill/` folder into your skills directory, then just ask: "I'm at People's Square, ¥30 budget, under 800kcal — find my optimum"

### Demo

Open `demo/index.html` (serve via any static HTTP server) — includes an in-browser JS port of the same solver.

## Architecture

```
User intent
  → mcp_client.py (JSON-RPC over Streamable HTTP, token from env var only)
  → build.py (menu + batch prices + meal details + nutrition matching)
  → solver.py (multi-constraint 0/1 knapsack DP, ~ms)
  → calculate-price (official price verification)
  → [optional, double-confirmed] create-order
```

- **Matching pipeline**: exact → normalized (digit-suffix relocation) → containment → combo default-sum (flagged `_estimated`) → category fallback
- **Rate-limit safety**: official 600 req/min cap, local token-bucket guard + 3-tier cache (menu 1h / price live / nutrition 24h)
- **Transaction safety**: action-layer tools (create-order etc.) require double confirmation; hard-coded amount threshold

## Disclaimer

This is an entry for the 2026 McDonald's Programmer Innovation Challenge, independently developed, not an official McDonald's product. Nutrition data comes from McDonald's official APIs, for reference only, and does not constitute medical or nutritional advice. Item info, prices and availability are subject to real-time results on official McDonald's channels.

## License

MIT
