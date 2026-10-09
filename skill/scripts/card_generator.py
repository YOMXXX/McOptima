"""McOptima 分享卡生成器 - 零依赖 SVG 卡片 (对比布局 + repo 链接)。

卡片规格: 1080×1350 (微信/朋友圈 4:5 竖版, 兼容 GitHub README 展示)
布局: 上下对比 (常规点法 vs 最优解) + 差值徽章 + 底部 repo 链接
输出: SVG (可直接嵌入 README / 网页), 可另存 .svg 文件

注意: SVG 内不含任何用户个人信息; 数据为脱敏的门店聚合数据。
"""

from __future__ import annotations

import html
from typing import Any

from solver import Constraints, Solution

CARD_W, CARD_H = 1080, 1350
REPO_URL = "github.com/YOMXXX/McOptima"
MCD_RED = "#DA0505"
DARK = "#1A1A1A"
LIGHT = "#FAFAFA"
GREEN = "#0F8A3C"
GRAY = "#9B9B9B"


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def generate_card(
    sol: Solution,
    c: Constraints,
    baseline_name: str = "常规点法",
    baseline_price: float = 0.0,
    baseline_kcal: int = 0,
    baseline_protein: float = 0.0,
    store_label: str = "麦当劳门店",
) -> str:
    """生成对比分享卡 SVG。

    baseline_* : 对比锚点 (如用户平时点的巨无霸套餐), 缺省时用 "App 默认推荐"
    """
    saved_money = round(baseline_price - sol.total_price, 1) if baseline_price else 0.0
    saved_kcal = baseline_kcal - sol.total_kcal if baseline_kcal else 0
    gained_protein = round(sol.total_protein - baseline_protein, 1) if baseline_protein else 0.0

    # 方案商品行 (最多 6 行)
    item_rows = []
    y = 0
    for it, q in sol.items[:6]:
        qty = f" ×{q}" if q > 1 else ""
        item_rows.append(
            f'<text x="90" y="{700 + y * 62}" font-size="34" fill="{DARK}" font-weight="600">'
            f'{_esc(it.name)}{qty}</text>'
            f'<text x="990" y="{700 + y * 62}" font-size="34" fill="{GRAY}" text-anchor="end">'
            f'¥{it.price:.1f}</text>'
        )
        y += 1

    badge = ""
    if saved_money > 0 and saved_kcal > 0:
        badge = f"省 ¥{saved_money} · 少 {saved_kcal} kcal"
    elif saved_money > 0:
        badge = f"省 ¥{saved_money}"
    elif saved_kcal > 0:
        badge = f"少 {saved_kcal} kcal"

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_W}" height="{CARD_H}" viewBox="0 0 {CARD_W} {CARD_H}">
  <defs>
    <linearGradient id="hdr" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{MCD_RED}"/>
      <stop offset="1" stop-color="#B00404"/>
    </linearGradient>
  </defs>

  <rect width="{CARD_W}" height="{CARD_H}" fill="{LIGHT}"/>

  <!-- 头部 -->
  <rect width="{CARD_W}" height="230" fill="url(#hdr)"/>
  <text x="90" y="105" font-size="58" fill="#FFF" font-weight="800">McOptima</text>
  <text x="90" y="165" font-size="34" fill="#FFD6D6">麦门最优解引擎 · {_esc(store_label)}</text>
  <text x="90" y="205" font-size="24" fill="#FFB3B3">预算 ¥{c.budget:.0f} | 热量≤{c.kcal_cap}kcal{f" | 蛋白≥{c.protein_floor:.0f}g" if c.protein_floor else ""}</text>

  <!-- 对比区: 常规点法 -->
  <rect x="60" y="290" width="960" height="180" rx="20" fill="#FFF" stroke="#E5E5E5" stroke-width="2"/>
  <text x="100" y="360" font-size="36" fill="{GRAY}" font-weight="700">通常这么点</text>
  <text x="100" y="425" font-size="42" fill="{DARK}" font-weight="800">{_esc(baseline_name)}</text>
  <text x="980" y="425" font-size="40" fill="{GRAY}" text-anchor="end" font-weight="700">¥{baseline_price:.1f} · {baseline_kcal}kcal</text>

  <!-- 箭头 -->
  <text x="540" y="545" font-size="52" fill="{MCD_RED}" text-anchor="middle" font-weight="900">↓ 全局最优解</text>

  <!-- 最优解区 -->
  <rect x="60" y="590" width="960" height="{120 + len(sol.items[:6]) * 62 + 40}" rx="20" fill="#FFF" stroke="{MCD_RED}" stroke-width="3"/>
  <text x="100" y="665" font-size="36" fill="{MCD_RED}" font-weight="800">McOptima 方案 (满足感 {sol.score})</text>
  {''.join(item_rows)}
  <line x1="90" y1="{700 + len(sol.items[:6]) * 62 + 10}" x2="990" y2="{700 + len(sol.items[:6]) * 62 + 10}" stroke="#EEE" stroke-width="2"/>
  <text x="100" y="{700 + len(sol.items[:6]) * 62 + 70}" font-size="44" fill="{DARK}" font-weight="800">合计 ¥{sol.total_price:.1f}</text>
  <text x="990" y="{700 + len(sol.items[:6]) * 62 + 70}" font-size="38" fill="{DARK}" text-anchor="end" font-weight="700">{sol.total_kcal}kcal · 蛋白{sol.total_protein:.0f}g</text>

  <!-- 差值徽章 -->
  <rect x="60" y="{590 + 120 + len(sol.items[:6]) * 62 + 40 + 40}" width="960" height="110" rx="55" fill="#E8F5EC"/>
  <text x="540" y="{590 + 120 + len(sol.items[:6]) * 62 + 40 + 40 + 70}" font-size="46" fill="{GREEN}" text-anchor="middle" font-weight="800">{_esc(badge) if badge else f'多 {gained_protein}g 蛋白' if gained_protein > 0 else '同样的钱，更优的解'}</text>

  <!-- 底部 -->
  <rect x="0" y="{CARD_H - 130}" width="{CARD_W}" height="130" fill="{DARK}"/>
  <text x="90" y="{CARD_H - 75}" font-size="32" fill="#FFF" font-weight="600">用运筹学穷举麦当劳菜单</text>
  <text x="90" y="{CARD_H - 35}" font-size="28" fill="#8C8C8C">{REPO_URL}</text>
  <text x="990" y="{CARD_H - 35}" font-size="24" fill="#8C8C8C" text-anchor="end">数据: 麦当劳官方MCP · 仅供参考</text>
</svg>"""
    return svg


def save_card(svg: str, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from mcp_client import McdMcpClient, McdService
    from build import build_food_items
    from substitute import find_target
    from solver import solve

    store = sys.argv[1] if len(sys.argv) > 1 else "1450713"
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join("..", "..", "assets", "card_demo.svg")

    svc = McdService(McdMcpClient(), cache_dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "cache"))
    items = build_food_items(svc, store, max_details=100)

    c = Constraints(budget=30, kcal_cap=800, protein_floor=25)
    sol = solve(items, c, top_k=1)[0]

    # 对比锚点: 巨无霸套餐 (经典点法)
    baseline = find_target("精选单人餐三件套", items)
    bp, bk, bpr = (baseline.price, baseline.kcal, baseline.protein) if baseline else (36.5, 949, 31)

    svg = generate_card(
        sol, c,
        baseline_name="巨无霸三件套套餐",
        baseline_price=bp, baseline_kcal=bk, baseline_protein=bpr,
        store_label="上海·人民广场",
    )
    os.makedirs(os.path.dirname(out), exist_ok=True)
    save_card(svg, out)
    print(f"✅ 分享卡已生成: {out}")
    print(f"   方案: {sol.name} (¥{sol.total_price:.1f})")
