"""McOptima 券与积分规划 - 领券建议 + 积分价值计算 + 抽奖期望值。

数据源 (麦当劳 MCP):
- query-store-coupons : 门店可用券 (指定 storeCode+orderType+beType)
- available-coupons   : 麦麦省可领券 (需先 auto-bind-coupons 领取, 交易类)
- query-my-coupons    : 用户卡包券
- query-my-account    : 积分账户 (可用/累计/冻结/即将过期)
- query-lottery-info  : 积分抽奖活动 (奖品/消耗/剩余次数)

原则: 只做查询与建议, 领券(auto-bind-coupons)与抽奖(draw-lottery)为交易类,
必须用户明确确认后才调用 (由 SKILL.md 安全规则约束)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CouponAdvice:
    title: str
    coupon_id: str
    products: list[str]
    source: str          # store / maimai / wallet
    action: str          # "点餐时选用" / "建议领取" / "已有可用"


def analyze_store_coupons(coupons: list[dict[str, Any]]) -> list[CouponAdvice]:
    """解析 query-store-coupons 结果为建议列表."""
    out = []
    for cp in coupons or []:
        prods = [p.get("productName", "") for p in cp.get("products", [])]
        out.append(CouponAdvice(
            title=cp.get("title", ""),
            coupon_id=cp.get("couponId", ""),
            products=prods,
            source="store",
            action="点餐时选用",
        ))
    return out


@dataclass
class PointsReport:
    available: int = 0
    total: int = 0
    expiring: int = 0
    expiring_date: str = ""
    suggestions: list[str] = None

    def __post_init__(self):
        if self.suggestions is None:
            self.suggestions = []


def analyze_points(account: dict[str, Any]) -> PointsReport:
    """解析 query-my-account 积分数据并给出保值建议."""
    r = PointsReport(
        available=account.get("availablePoints", 0),
        total=account.get("totalPoints", 0),
        expiring=account.get("expiringPoints", 0) or account.get("willExpirePoints", 0),
        expiring_date=account.get("expireDate", "") or account.get("expiringDate", ""),
    )
    if r.expiring > 0:
        r.suggestions.append(
            f"⚠️ 有 {r.expiring} 积分即将过期({r.expiring_date or '日期见App'}) - 优先用于兑换或抽奖, 避免清零"
        )
    if r.available >= 3000:
        r.suggestions.append("积分较多: 可考虑麦麦商城兑换实物/餐品券 (mall-points-products 查看商品)")
    elif r.available > 0:
        r.suggestions.append("积分可参与抽奖或兑换小额餐品券, 价值密度通常低于直接消费, 按需使用")
    else:
        r.suggestions.append("当前无可用积分, 消费累积即可")
    return r


def lottery_ev(lottery_info: dict[str, Any]) -> dict[str, Any] | None:
    """积分抽奖期望值估算。

    输入 query-lottery-info 的 data (含 prizeList / 消耗规则)。
    返回 {cost_points, ev_points, prizes: [(name, prob, value_estimate)], advice}
    价值估计用粗略档位: 实物按公示价值, 餐品券按面值, 谢谢参与=0。
    """
    prizes = lottery_info.get("prizeList") or lottery_info.get("prizes") or []
    if not prizes:
        return None
    cost = lottery_info.get("costPoints", 0) or lottery_info.get("consumePoints", 0)
    total_weight = 0
    rows = []
    for pz in prizes:
        name = pz.get("prizeName") or pz.get("name") or ""
        prob = pz.get("probability") or pz.get("rate") or 0
        # 概度可能是百分比(0-100)或小数(0-1)
        if prob and prob <= 1:
            prob = prob * 100
        value = pz.get("valueEstimate") or pz.get("worth") or 0
        total_weight += prob
        rows.append((name, prob, value))
    if total_weight <= 0:
        return None
    # 归一化 (若公示概率不含谢谢参与, 按比例归一)
    ev = sum(p * v for _, p, v in rows) / max(total_weight, 100) * 100 if total_weight > 100 else sum(p * v for _, p, v in rows) / 100
    advice = (
        f"抽奖期望值 ≈ ¥{ev:.2f}/次, 消耗 {cost} 积分"
        f" → 每万积分期望回报 ¥{ev / max(cost, 1) * 10000:.0f}"
    )
    return {"cost_points": cost, "ev": ev, "prizes": rows, "advice": advice}


def format_coupon_report(
    store_advices: list[CouponAdvice],
    points: PointsReport | None = None,
    lottery: dict[str, Any] | None = None,
) -> str:
    lines = ["券与积分规划", "=" * 40]
    if store_advices:
        lines.append("【门店可用券】")
        for a in store_advices:
            lines.append(f"  · {a.title} → {a.action} (适用: {', '.join(a.products[:3]) or '全场'})")
    else:
        lines.append("【门店可用券】当前无")
    if points:
        lines.append("")
        lines.append(f"【积分】可用 {points.available} / 累计 {points.total}")
        for s in points.suggestions:
            lines.append(f"  {s}")
    if lottery:
        lines.append("")
        lines.append(f"【抽奖期望】{lottery['advice']}")
    lines.append("")
    lines.append("—— 券信息以麦当劳官方实时数据为准; 领券/抽奖操作需你确认后执行")
    return "\n".join(lines)


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from mcp_client import McdMcpClient, McdService

    store = sys.argv[1] if len(sys.argv) > 1 else "1450713"
    svc = McdService(McdMcpClient(), cache_dir=os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache"))

    coupons = svc.store_coupons(store)
    advices = analyze_store_coupons(coupons)

    points = None
    lottery = None
    try:
        acct = svc.query(f"account", "query-my-account", {}, max_age_sec=300)
        points = analyze_points(acct or {})
    except Exception as e:
        print(f"(积分查询不可用: {str(e)[:60]})")
    try:
        li = svc.query("lottery", "query-lottery-info", {}, max_age_sec=300)
        lottery = lottery_ev(li or {})
    except Exception as e:
        print(f"(抽奖信息不可用: {str(e)[:60]})")

    print(format_coupon_report(advices, points, lottery))
