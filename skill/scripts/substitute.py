"""McOptima 平替换算器 - "想吃 X 但不想超 Y kcal" 的替代方案求解。

思路:
1. 模糊匹配用户想吃的餐品 (直接匹配或套餐默认展开)
2. 以该餐品的满足感为基准, 在热量上限(用户目标)内求满足感最大组合
3. 输出对比: 目标餐品 vs 替代组合 (热量差/价格差/蛋白差)

输出仅供参考, 不构成医疗或营养建议。
"""

from __future__ import annotations

from typing import Any

from solver import Constraints, FoodItem, Solution, solve


def find_target(name: str, items: list[FoodItem]) -> FoodItem | None:
    """在餐品池中模糊匹配目标餐品 (包含式匹配, 取最短名避免歧义)."""
    direct = [it for it in items if it.name == name]
    if direct:
        return direct[0]
    contains = [it for it in items if name in it.name or it.name in name]
    if contains:
        return min(contains, key=lambda it: len(it.name))
    # 逐字匹配度排序
    def overlap(a: str, b: str) -> int:
        return sum(1 for ch in set(a) if ch in set(b))
    scored = sorted(items, key=lambda it: -overlap(name, it.name))
    if scored and overlap(name, scored[0].name) >= max(2, len(set(name)) // 2):
        return scored[0]
    return None


def substitute(
    target: FoodItem,
    items: list[FoodItem],
    kcal_cap: int | None = None,
    budget: float | None = None,
) -> dict[str, Any] | None:
    """找 target 的平替组合。

    kcal_cap: 替代组合的热量上限 (默认 = target.kcal - 100)
    budget: 替代组合的预算上限 (默认 = target.price)
    返回 {target, sub: Solution, kcal_saved, money_saved, protein_diff}
    """
    cap = kcal_cap if kcal_cap is not None else max(200, target.kcal - 100)
    bud = budget if budget is not None else target.price
    # 目标餐品本身不入池 (否则最优解就是它自己)
    pool = [it for it in items if it.code != target.code]
    try:
        c = Constraints(budget=bud, kcal_cap=cap, protein_floor=0)
        sols = solve(pool, c, top_k=1)
    except ValueError:
        return None
    if not sols:
        return None
    sub = sols[0]
    return {
        "target": target,
        "sub": sub,
        "kcal_saved": target.kcal - sub.total_kcal,
        "money_saved": round(target.price - sub.total_price, 1),
        "protein_diff": round(sub.total_protein - target.protein, 1),
        "satisfaction_ratio": round(sub.score / target.base_score * 100, 1) if target.base_score > 0 else None,
    }


def format_sub_result(r: dict[str, Any]) -> str:
    t: FoodItem = r["target"]
    s: Solution = r["sub"]
    lines = [
        f"想吃: {t.name} (¥{t.price:.1f} / {t.kcal}kcal / 蛋白{t.protein:.0f}g)",
        f"平替: {s.name}",
        f"  ¥{s.total_price:.1f} / {s.total_kcal}kcal / 蛋白{s.total_protein:.0f}g",
        "",
        f"热量节省 {r['kcal_saved']} kcal | 价格差 ¥{r['money_saved']:+.1f} | 蛋白差 {r['protein_diff']:+.1f}g",
    ]
    if r["satisfaction_ratio"]:
        lines.append(f"满足感保留 {r['satisfaction_ratio']}%")
    lines.append("—— 营养数据来自麦当劳官方接口，仅供参考")
    return "\n".join(lines)


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from mcp_client import McdMcpClient, McdService
    from build import build_food_items

    store = sys.argv[1] if len(sys.argv) > 1 else "1450713"
    target_name = sys.argv[2] if len(sys.argv) > 2 else "巨无霸"
    kcal_cap = int(sys.argv[3]) if len(sys.argv) > 3 else None

    svc = McdService(McdMcpClient(), cache_dir=os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache"))
    items = build_food_items(svc, store, max_details=100)
    t = find_target(target_name, items)
    if not t:
        print(f"未找到餐品: {target_name}")
        sys.exit(1)
    print(f"[McOptima 平替换算] 门店 {store}")
    r = substitute(t, items, kcal_cap=kcal_cap)
    if r:
        print(format_sub_result(r))
    else:
        print("无可行平替 (约束过紧), 试试放宽热量上限")
