"""数据装配器: 把 MCP 原始数据拼成求解器需要的 FoodItem 列表。

数据源:
- query-meals        → 门店菜单 (分类 + 餐品编码)
- query-meal-detail  → 餐品名称/价格/套餐结构
- list-nutrition-foods → 营养成分 (名称模糊匹配)

注意: MCP 菜单接口只返回编码, 需要逐个调 query-meal-detail 拿名称与价格。
"""

from __future__ import annotations

import re
from typing import Any

from mcp_client import McdService
from solver import Constraints, FoodItem, Solution, solve, explain

# 营养表名称 → 菜单餐品的常见别名映射 (模糊匹配兜底)
_ALIAS = {
    "麦乐鸡5块": ["麦乐鸡5块", "麦乐鸡*5块", "麦乐鸡(5块)"],
    "圆筒冰淇淋": ["圆筒冰淇淋", "圆筒"],
    "大薯条": ["大薯条"],
    "中薯条": ["中薯条"],
    "小薯条": ["小薯条"],
}


def parse_nutrition(data: Any) -> dict[str, dict[str, Any]]:
    """解析 list-nutrition-foods 的行式数据: '名称,desc,kJ,kcal,蛋白,脂肪,碳水,钠,钙'"""
    out: dict[str, dict[str, Any]] = {}
    if isinstance(data, str):
        # 格式: "[160]{productName,...}:\n  名称,null,1288,308,16,16,24,781,213\n ..."
        body = data.split("}:", 1)[-1]
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 9:
                continue
            name = parts[0]
            try:
                out[name] = {
                    "kcal": int(float(parts[3] or 0)),
                    "protein": float(parts[4] or 0),
                    "fat": float(parts[5] or 0),
                    "carb": float(parts[6] or 0),
                    "sodium": int(float(parts[7] or 0)),
                    "calcium": int(float(parts[8] or 0)),
                }
            except ValueError:
                continue
    elif isinstance(data, list):
        for row in data:
            out[row.get("productName", "")] = {
                "kcal": row.get("energyKcal", 0),
                "protein": row.get("protein", 0),
                "fat": row.get("fat", 0),
                "carb": row.get("carbohydrate", 0),
                "sodium": row.get("sodium", 0),
                "calcium": row.get("calcium", 0),
            }
    return out


def _norm(name: str) -> str:
    """名称归一化: 去符号/空格, 数字后缀标准化 (麦乐鸡5块 == 5块麦乐鸡 == 麦乐鸡*5块)."""
    s = re.sub(r"[\s*（）()·™“”\"' -]", "", name)
    # '5块麦乐鸡' -> '麦乐鸡5块' (数字搬家到末尾)
    m = re.match(r"^(\d+)(块|个|份)?(.+)$", s)
    if m and len(m.group(3)) > 1:
        s = m.group(3) + m.group(1)
    return s


def _kw_set(name: str) -> set[str]:
    """提取名称核心词 (去掉规格词)."""
    s = _norm(name)
    for pat in [r"(中杯|大杯|小杯|大薯条|中薯条|小薯条|迷你薯条|5块|4块|2块)"]:
        s = re.sub(pat, "", s)
    return s


def _match_nutrition(name: str, nutrition: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """名称模糊匹配营养表。策略: 精确 -> 归一化精确 -> 归一化包含(长度差受限) -> 核心词包含."""
    if not name:
        return None
    if name in nutrition:
        return nutrition[name]
    n = _norm(name)
    # 归一化精确
    norm_map = {_norm(k): v for k, v in nutrition.items()}
    if n in norm_map:
        return norm_map[n]
    # 归一化包含 (菜单名 ⊆ 营养名 或反之, 长度差≤6 容纳规格后缀)
    for k, v in norm_map.items():
        if len(n) >= 2 and (n in k or k in n) and abs(len(n) - len(k)) <= 6:
            return v
    return None


def fetch_prices(svc: McdService, store_code: str, codes: list[str], batch_size: int = 20) -> dict[str, float]:
    """批量用 calculate-price 拉取餐品价格 (返回 分→元 换算后的 {code: price}).

    calculate-price 的 items 用 productCode 字段; 返回 price 单位为分。
    一次请求可带多个商品, 分批控制单次 payload。
    """
    prices: dict[str, float] = {}
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        try:
            data = svc.calculate_price(store_code, [{"productCode": c, "quantity": 1} for c in batch])
        except Exception:
            continue
        for p in (data or {}).get("productList", []):
            pc = p.get("productCode")
            sub = p.get("subtotal", 0)
            if pc and sub:
                prices[pc] = sub / 100.0
    return prices


DEFAULT_NUTRITION_BY_CATEGORY = {
    # 分类兜底营养估计 (每份均值) - 仅为无官方营养数据的新品兜底, 输出会标注
    "饮品": {"kcal": 150, "protein": 2, "fat": 2, "carb": 30, "sodium": 30},
    "麦咖啡™": {"kcal": 180, "protein": 4, "fat": 5, "carb": 25, "sodium": 60},
    "小食甜品/其他": {"kcal": 250, "protein": 5, "fat": 12, "carb": 30, "sodium": 250},
    "小食拼盘/多人餐": {"kcal": 450, "protein": 20, "fat": 22, "carb": 40, "sodium": 700},
    "开心乐园": {"kcal": 400, "protein": 15, "fat": 15, "carb": 50, "sodium": 550},
}


def estimate_from_rounds(detail: dict[str, Any], nutrition: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """套餐默认选择的营养加总; 命中数不足时用分类兜底估计并打标."""
    kcal = p = f = cb = sd = 0.0
    hits = 0
    for rnd in detail.get("rounds", []):
        for ch in rnd.get("choices", []):
            if ch.get("isDefault"):
                cn = _match_nutrition(ch.get("name", ""), nutrition)
                if cn:
                    kcal += cn["kcal"]; p += cn["protein"]; f += cn["fat"]
                    cb += cn["carb"]; sd += cn["sodium"]; hits += 1
    if hits:
        # 部分命中且至少覆盖主轮次 → 可用 (置信度随命中率下降)
        return {"kcal": int(kcal), "protein": p, "fat": f, "carb": cb, "sodium": int(sd), "_estimated": hits < len(detail.get("rounds", []))}
    return None


def build_food_items(
    svc: McdService,
    store_code: str,
    max_details: int = 60,
    allow_categories: set[str] | None = None,
    multi_qty_categories: set[str] | None = None,
) -> list[FoodItem]:
    """拉取菜单 + 逐餐品详情, 装配 FoodItem 列表 (带本地缓存)."""
    menu = svc.menu(store_code)
    nutrition = parse_nutrition(svc.nutrition())
    multi_qty_categories = multi_qty_categories or {"饮品", "麦咖啡™", "小食甜品/其他"}

    items: list[FoodItem] = []
    # 第一步: 收集所有餐品编码 + 名称 (先取详情中的名称)
    code_cat: list[tuple[str, str, list[str]]] = []
    for cat in menu.get("categories", []):
        cat_name = cat.get("name", "").replace("\n", "")
        if allow_categories is not None and cat_name not in allow_categories:
            continue
        for meal in cat.get("meals", []):
            code = meal.get("code")
            if code:
                code_cat.append((code, cat_name, meal.get("tags", [])))

    # 第二步: 批量拉价格 (calculate-price 一次可带多商品)
    all_codes = [c for c, _, _ in code_cat][:max_details * 2] if max_details else [c for c, _, _ in code_cat]
    prices = fetch_prices(svc, store_code, all_codes)

    # 第三步: 逐餐品拉详情获取名称 + 套餐结构, 配营养数据
    fetched = 0
    for code, cat_name, tags in code_cat:
        if fetched >= max_details:
            break
        price = prices.get(code)
        if not price:
            continue  # 无价格 = 不可售
        try:
            detail = svc.meal_detail(store_code, code)
        except Exception:
            continue
        fetched += 1
        name = detail.get("name", "")
        if not name:
            continue
        nut = _match_nutrition(name, nutrition)
        if nut is None:
            # 套餐: 默认选择的营养加总 (部分命中会打 _estimated 标)
            nut = estimate_from_rounds(detail, nutrition)
        if nut is None:
            # 分类兜底估计 (新品无营养数据), 打标
            fallback = DEFAULT_NUTRITION_BY_CATEGORY.get(cat_name)
            if fallback is None:
                continue
            nut = dict(fallback)
            nut["_estimated"] = True
        items.append(
            FoodItem(
                code=code,
                name=name,
                price=float(price),
                kcal=int(nut["kcal"]),
                protein=float(nut["protein"]),
                fat=float(nut["fat"]),
                carb=float(nut["carb"]),
                sodium=int(nut["sodium"]),
                category=cat_name,
                tags=tags,
                max_qty=3 if cat_name in multi_qty_categories else 1,
            )
        )
    return items


def optimize(
    svc: McdService,
    store_code: str,
    constraints: Constraints,
    top_k: int = 3,
    **build_kwargs,
) -> list[Solution]:
    """端到端: 拉数据 → 装配 → 求解 → 返回 top-k 方案."""
    items = build_food_items(svc, store_code, **build_kwargs)
    if not items:
        raise ValueError(f"门店 {store_code} 未装配出任何可计算餐品, 请检查菜单/营养数据匹配")
    return solve(items, constraints, top_k=top_k)


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from mcp_client import McdMcpClient

    store = sys.argv[1] if len(sys.argv) > 1 else "1450713"
    budget = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    kcal_cap = int(sys.argv[3]) if len(sys.argv) > 3 else 800
    protein = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0

    client = McdMcpClient()  # 从 MCD_MCP_TOKEN 环境变量读取
    svc = McdService(client, cache_dir=os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache"))
    c = Constraints(budget=budget, kcal_cap=kcal_cap, protein_floor=protein)
    print(f"[McOptima] 门店 {store} | 预算 ¥{budget} | 热量上限 {kcal_cap}kcal | 蛋白下限 {protein}g\n")
    for i, sol in enumerate(optimize(svc, store, c), 1):
        print(f"—— 方案 {i} ——")
        print(explain(sol, c))
        print()
