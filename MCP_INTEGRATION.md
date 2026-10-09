# MCP Integration - 麦当劳 MCP 能力接入说明

本项目基于**麦当劳中国官方 MCP Server** 构建，真实调用以下工具实现业务价值。

## 接入信息

| 项 | 值 |
|---|---|
| Server | 麦当劳中国 MCP Server (`mcd-mcp` v1.0.0+) |
| 地址 | `https://mcp.mcd.cn` |
| 协议 | Streamable HTTP (JSON-RPC 2.0) |
| 鉴权 | `Authorization: Bearer <MCP_TOKEN>`（Token 于 [open.mcd.cn/mcp](https://open.mcd.cn/mcp) 申请，仅存于环境变量 `MCD_MCP_TOKEN`） |
| 限流 | 600 req/min/Token（本项目内置本地令牌桶保护 + 三级缓存，实际调用量远低于上限） |

## 实际使用的工具

### 感知层（数据查询）

| Tool | 用途 | 调用时机 |
|---|---|---|
| `query-nearby-stores` | 查询用户附近门店，获取 storeCode/beCode | 会话开始定位门店 |
| `query-meals` | 拉取门店完整菜单（14 分类 / 111 餐品） | 构建求解池（缓存 1h） |
| `query-meal-detail` | 餐品详情：名称、套餐结构（rounds/choices）、特制选项 | 装配餐品名称与套餐组成 |
| `list-nutrition-foods` | 158 项官方营养数据（能量/蛋白/脂肪/碳水/钠/钙） | 求解器核心营养输入（缓存 24h） |
| `query-store-coupons` | 门店可用优惠券 | 券优化模块 |
| `available-coupons` | 麦麦省可领券列表 | 省钱规划 |
| `query-my-coupons` | 用户卡包券 | 个性化券匹配 |
| `query-my-account` | 积分账户 | 积分价值模块 |
| `campaign-calendar` | 当月营销活动日历 | 活动推荐 |
| `order-list` / `query-order` | 历史订单/订单详情 | 下单后状态跟踪 |
| `now-time-info` | 服务器时间 | 深夜补给场景的咖啡因时间窗判断 |
| `delivery-query-addresses` / `delivery-query-stores` | 外送地址与可配送门店 | 麦乐送场景 |

### 规划层（价格计算）

| Tool | 用途 | 调用时机 |
|---|---|---|
| `calculate-price` | 批量计算商品组合价格（券前/券后、原价/折扣） | ① 装配阶段批量拉菜单价格；② 方案产出后验价；③ 下单前终价确认 |

### 行动层（交易，双确认后调用）

| Tool | 用途 | 安全机制 |
|---|---|---|
| `create-order` | 创建订单返回支付链接 | 方案展示 → 用户明确确认 → 金额>¥150 二次复述 |
| `cancel-order` | 取消订单 | 用户反悔兜底 |
| `auto-bind-coupons` | 一键领取麦麦省全部可领券 | 用户明确要求时 |

> 团餐扩展（规划中）：`query-meal-assistance`（助餐服务）、`query-promotions`（满减/满折规则，beType=6）。

## 调用流程

```
用户意图
  │
  ├─ 定位 ──► query-nearby-stores ──► storeCode
  │                                        │
  ├─ 数据 ──► query-meals ──────────────┐  │
  │          calculate-price (批量价格) │  │
  │          query-meal-detail (逐餐品) ▼  │
  │          list-nutrition-foods ──► FoodItem 池
  │                                        │
  ├─ 求解 ──► solver.py (本地 DP, 不耗 API)
  │                                        │
  ├─ 验价 ──► calculate-price (top-1 方案) ──► 官方总价
  │                                        │
  └─ 交易 ──► [用户双确认] ──► create-order ──► 支付链接
                                    │
                                    └─► (异常) cancel-order
```

## 业务价值

1. **把官方数据变成决策**：麦当劳 MCP 提供了完整的菜单/营养/价格/券数据原子能力，但普通用户面对 111 个餐品 + 多维约束（预算/热量/蛋白）时无法手动求解。McOptima 在官方数据之上叠加运筹学求解层，把「数据查询」升级为「决策优化」。
2. **官方实时价格背书**：所有方案总价均经 `calculate-price` 实时验证，不出现「估算价」与实付价的偏差。
3. **营养数据全覆盖**：158 项官方营养数据 + 名称归一化匹配 + 套餐默认选择加总 + 分类兜底估计（打 `_estimated` 标记），保证求解池覆盖率。
4. **安全交易设计**：行动层工具与感知层隔离，双确认 + 金额阈值硬编码，防误下单与提示词注入。
