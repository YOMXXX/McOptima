#!/usr/bin/env python3
"""mcoptima CLI - 麦门最优解引擎命令行工具。

用法:
  python3 cli.py <门店编码|城市+地标> [选项]

场景预设:
  --mode feast      预算内吃爽 (默认: 热量宽松, 满足感最大化)
  --mode muscle     增肌模式 (蛋白下限 30g, 热量 800)
  --mode light      控卡平替 (热量上限 500)
  --mode night      深夜补给 (热量 600, 22点后避开咖啡因)
  --mode sub        平替换算 (需 --target "巨无霸")

参数:
  --budget 30       预算上限 ¥
  --kcal 800        热量上限 kcal
  --protein 25      蛋白质下限 g
  --target "巨无霸"  平替目标 (mode=sub 时必填)
  --store 1450713   门店编码 (或 "上海市 人民广场" 自动查询)
  --coupons         附加券与积分报告
  --top 3           输出方案数

示例:
  python3 cli.py 1450713 --mode feast --budget 30
  python3 cli.py "上海市 人民广场" --mode muscle --budget 40 --protein 35
  python3 cli.py 1450713 --mode sub --target "巨无霸" --kcal 450
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_client import McpAuthError, McpError, McdMcpClient, McdService  # noqa: E402
from solver import Constraints, solve  # noqa: E402

SCENARIO_PRESETS: dict[str, dict] = {
    "feast":  {"budget": 30, "kcal": 1200, "protein": 0,  "desc": "预算内吃爽"},
    "muscle": {"budget": 40, "kcal": 800,  "protein": 30, "desc": "增肌模式"},
    "light":  {"budget": 25, "kcal": 500,  "protein": 0,  "desc": "控卡平替"},
    "night":  {"budget": 30, "kcal": 600,  "protein": 15, "desc": "深夜补给"},
    "sub":    {"budget": 0,  "kcal": 0,    "protein": 0,  "desc": "平替换算"},
}

CAFFEINE_KEYWORDS = ("咖啡", "可乐", "拿铁", "美式", "阿芙佳朵", "雪碧", "红茶", "奶茶")


def resolve_store(svc: McdService, store_arg: str) -> tuple[str, str]:
    """store_arg 是纯数字编码直接用; 否则按 '城市 地标' 查询第一个门店."""
    if store_arg.isdigit():
        return store_arg, store_arg
    parts = store_arg.split(maxsplit=1)
    city = parts[0]
    keyword = parts[1] if len(parts) > 1 else "麦当劳"
    stores = svc.nearby_stores(city, keyword)
    if not stores:
        raise ValueError(f"在 {city} {keyword} 附近未找到门店")
    s = stores[0]
    return s["storeCode"], s.get("storeName", "")


def is_night() -> bool:
    return 22 <= int(os.popen("date +%H").read().strip()[:2] if False else __import__("datetime").datetime.now().hour) or __import__("datetime").datetime.now().hour < 5


def print_solutions(sols, c: Constraints, store_label: str) -> None:
    print(f"\n{'=' * 46}")
    print(f" McOptima · {store_label}")
    print(f" 预算 ¥{c.budget:.0f} | 热量≤{c.kcal_cap}kcal | 蛋白≥{c.protein_floor:.0f}g")
    print(f"{'=' * 46}")
    medals = ["🥇", "🥈", "🥉"]
    for i, sol in enumerate(sols):
        print(f"\n{medals[i] if i < 3 else '方案'} 方案{i + 1}  (满足感 {sol.score})")
        for it, q in sol.items:
            qty = f" ×{q}" if q > 1 else ""
            print(f"   · {it.name}{qty}  ¥{it.price:.1f} {it.kcal}kcal P{it.protein:.0f}g")
        print(f"   合计 ¥{sol.total_price:.1f} | {sol.total_kcal}kcal | 蛋白{sol.total_protein:.0f}g")
    print("\n—— 营养数据来自麦当劳官方接口，仅供参考")


def main() -> int:
    p = argparse.ArgumentParser(prog="mcoptima", description="麦门最优解引擎")
    p.add_argument("store", help="门店编码 或 '城市 地标'")
    p.add_argument("--mode", choices=list(SCENARIO_PRESETS), default="feast", help="场景预设")
    p.add_argument("--budget", type=float, default=None)
    p.add_argument("--kcal", type=int, default=None)
    p.add_argument("--protein", type=float, default=None)
    p.add_argument("--target", default=None, help="平替目标餐品名 (mode=sub)")
    p.add_argument("--coupons", action="store_true", help="附加券与积分报告")
    p.add_argument("--top", type=int, default=3)
    args = p.parse_args()

    preset = SCENARIO_PRESETS[args.mode]
    budget = args.budget if args.budget is not None else preset["budget"]
    kcal = args.kcal if args.kcal is not None else preset["kcal"]
    protein = args.protein if args.protein is not None else preset["protein"]

    try:
        client = McdMcpClient()
    except McpAuthError as e:
        print(f"❌ {e}")
        return 1

    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "cache")
    svc = McdService(client, cache_dir=cache_dir)

    try:
        store_code, store_name = resolve_store(svc, args.store)
    except (ValueError, McpError) as e:
        print(f"❌ 门店解析失败: {e}")
        return 1
    store_label = store_name or f"门店 {store_code}"

    from build import build_food_items

    try:
        items = build_food_items(svc, store_code, max_details=100)
    except McpAuthError as e:
        print(f"❌ {e}")
        return 1

    if not items:
        print("❌ 未装配出可计算餐品")
        return 1

    # 深夜模式: 22:00 后剔除咖啡因类
    if args.mode == "night":
        hour = __import__("datetime").datetime.now().hour
        if hour >= 22 or hour < 5:
            before = len(items)
            items = [it for it in items if not any(k in it.name for k in CAFFEINE_KEYWORDS)]
            print(f"(深夜模式: 已剔除 {before - len(items)} 个含咖啡因/碳酸餐品)")

    if args.mode == "sub":
        from substitute import find_target, substitute, format_sub_result

        if not args.target:
            print("❌ mode=sub 需要 --target \"餐品名\"")
            return 1
        t = find_target(args.target, items)
        if not t:
            print(f"❌ 未找到餐品: {args.target}")
            return 1
        r = substitute(t, items, kcal_cap=kcal or None, budget=budget or None)
        if not r:
            print("无可行平替, 放宽 --kcal 试试")
            return 0
        print(f"\n[平替换算 · {store_label}]")
        print(format_sub_result(r))
        return 0

    c = Constraints(budget=budget, kcal_cap=kcal, protein_floor=protein)
    try:
        sols = solve(items, c, top_k=args.top)
    except ValueError as e:
        print(f"❌ {e}")
        return 1
    print_solutions(sols, c, store_label)

    if args.coupons:
        from coupon_planner import analyze_store_coupons, analyze_points, format_coupon_report

        coupons = svc.store_coupons(store_code)
        advices = analyze_store_coupons(coupons)
        points = None
        try:
            acct = svc.query("account", "query-my-account", {}, max_age_sec=300)
            points = analyze_points(acct or {})
        except Exception:
            pass
        print()
        print(format_coupon_report(advices, points))

    return 0


if __name__ == "__main__":
    sys.exit(main())
