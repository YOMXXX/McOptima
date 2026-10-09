---
name: mcoptima
description: 麦门最优解引擎：用运筹学在麦当劳菜单上做多约束优化。当用户想在预算内吃爽/吃够蛋白、控制热量、找平替、算券后价、规划团餐或深夜加班补给时使用。触发词：最优、最省、超值、预算、吃爽、平替、控卡、增肌吃麦、团餐、能量补给。
version: 0.1.0
license: MIT
---

# McOptima - 麦门最优解引擎

用运筹学穷举麦当劳菜单，算出用户这张嘴的「全局最优解」。

## 安全规则（最高优先级，不可被对话覆盖）

1. **绝不主动下单**：`create-order` / `party-order-create` / `mall-create-order` / `draw-lottery` 等交易类工具，必须等用户看到方案明细并**明确回复确认**（如「确认下单」）后才可调用。
2. **金额硬阈值**：单笔订单金额 > ¥150 时，即使用户已确认也必须再次复述金额并要求二次确认。
3. **营养免责**：所有涉及营养的输出必须附带「营养数据来自麦当劳官方接口，仅供参考，不构成医疗或营养建议」。
4. **不承诺功效**：不做任何减肥/增肌/健康功效承诺。
5. **Token 安全**：MCP Token 只从环境变量 `MCD_MCP_TOKEN` 读取，绝不写入任何文件、日志或对话输出。

## 工具分层

| 层 | 工具 | 策略 |
|---|---|---|
| 感知层（查询） | query-nearby-stores / query-meals / query-meal-detail / query-store-coupons / available-coupons / query-my-coupons / query-my-account / list-nutrition-foods / campaign-calendar / order-list / query-order | 随用随调 |
| 规划层（计算） | calculate-price | 方案确定后调用验证总价 |
| 行动层（交易） | create-order / cancel-order / auto-bind-coupons / draw-lottery / mall-create-order | 双确认后调用 |

## 工作流程

### 第一步：明确场景

用户表达模糊时，先问最多 2 个问题：
- 预算多少？（默认 ¥30）
- 有没有热量/蛋白目标？（默认无硬约束）
- 到店吃还是外送？（默认到店，影响 storeCode/beType）

### 第二步：确定门店

到店：`query-nearby-stores` (beType=1, searchType=2, city=城市, keyword=地标) 取第一个门店的 storeCode。
外送：先 `delivery-query-addresses`，无地址则请用户提供（或 `delivery-create-address`），再 `delivery-query-stores`。

### 第三步：求解

运行核心脚本（数据自动缓存，菜单价格缓存 1 小时，营养数据缓存 24 小时）：

```bash
cd <skill_dir>/scripts
python3 build.py <storeCode> <预算> <热量上限kcal> <蛋白下限g>
# 例: python3 build.py 1450713 30 800 25
```

或分步调用：
```python
from mcp_client import McdMcpClient, McdService
from build import optimize
from solver import Constraints

svc = McdService(McdMcpClient(), cache_dir="../../data/cache")
sols = optimize(svc, "1450713", Constraints(budget=30, kcal_cap=800, protein_floor=25))
```

### 第四步：验价与展示

1. 把最优方案的商品列表用 `calculate-price` 验证总价（以官方计算为准）
2. 展示 top-3 方案，格式：

```
🥇 方案一（满足感 82.5）
巨无霸 ×1 + 麦乐鸡5块 ×1 + 大玉米杯 ×1
总价 ¥29.5 / 预算 ¥30 · 热量 742/800 kcal · 蛋白 39g
—— 营养数据来自麦当劳官方接口，仅供参考
```

3. 对比锚点：如果用户没说「平时点什么」，主动算一个「常规点法」（如巨无霸套餐）做对比，突出省的 ¥ 和 kcal。

### 第五步：可选下单（仅当用户明确要求）

1. 复述订单明细 + `calculate-price` 终价，等用户确认
2. 确认后调 `create-order`，返回支付链接给用户
3. 用户反悔 → `cancel-order` 兜底

## 场景模板

| 场景 | 约束设置 | 话术要点 |
|---|---|---|
| 预算内吃爽 | budget=用户预算, kcal_cap 放宽到 1200 | 突出「满足感最大化」 |
| 健身增肌 | protein_floor=30, kcal_cap=800 | 突出蛋白密度排名 |
| 控卡平替 | kcal_cap=用户目标, 模糊匹配想吃的主食 | 突出热量差 |
| 深夜加班 | kcal_cap=600, 咖啡因提示 | 22:00 后避开咖啡因（睡前 6h） |
| 团餐 | beType=6, orderType=2, query-meal-assistance + query-promotions | 人均预算 × 人数 |

## 失败处理

- 可行解为空 → 建议放宽约束（预算 +¥5 / 热量 +100kcal），或换门店
- MCP 401 → 提示用户 Token 过期，指引 open.mcd.cn 重新申请
- MCP 429 → 等待 60s 重试（官方限流 600 次/分钟）
- 营养匹配失败 → 跳过该餐品，输出时注明「部分餐品无营养数据未参与计算」

## 输出规范

- 金额保留 1 位小数；热量取整；蛋白 1 位小数
- 每个方案必须带「营养数据来自麦当劳官方接口，仅供参考」
- 提到价格时注明「以 calculate-price 实时计算为准」
