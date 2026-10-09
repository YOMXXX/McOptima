"""生成 README 用的终端风格 SVG 演示图（真实 CLI 输出）。"""

import html
import os

W, H = 900, 560
BG = "#1E1E2E"
FG = "#CDD6F4"
GREEN = "#A6E3A1"
RED = "#F38BA8"
YELLOW = "#F9E2AF"
BLUE = "#89B4FA"
GRAY = "#6C7086"

LINES = [
    ("cmd", "$ python3 cli.py \"上海市 人民广场\" --mode muscle --budget 40 --protein 35"),
    ("dim", ""),
    ("hdr", "══════════════════════════════════════════════════"),
    ("hdr", " McOptima · 麦当劳上海黄浦华旭国际大厦餐厅"),
    ("hdr", " 预算 ¥40 | 热量≤800kcal | 蛋白≥35g"),
    ("hdr", "══════════════════════════════════════════════════"),
    ("dim", ""),
    ("ok", "🥇 方案1  (满足感 780.76)"),
    ("item", "   · 蘸酱麦麦脆汁鸡   ¥11.9  328kcal  P21g"),
    ("item", "   · 那么大鸡排(椒盐) ¥14.0  385kcal  P24g"),
    ("item", "   · 小杯玉米杯       ¥13.0   53kcal  P2g"),
    ("sum", "   合计 ¥38.9 | 766kcal | 蛋白47g"),
    ("dim", ""),
    ("ok2", "🥈 方案2  (满足感 680.94)"),
    ("item", "   · 人气经典随心配   ¥14.9  429kcal  P27g"),
    ("item", "   · 麦麦脆汁鸡1块    ¥15.0  328kcal  P21g"),
    ("item", "   · 小杯鲜萃咖啡     ¥9.5   15kcal  P1g"),
    ("sum", "   合计 ¥39.4 | 772kcal | 蛋白49g"),
    ("dim", ""),
    ("note", "—— 营养数据来自麦当劳官方接口，仅供参考"),
]

COLORS = {
    "cmd": GREEN, "hdr": BLUE, "ok": YELLOW, "ok2": YELLOW,
    "item": FG, "sum": FG, "note": GRAY, "dim": GRAY,
}


def esc(s):
    return html.escape(s, quote=True)


def main():
    lines = []
    y = 0
    for kind, text in LINES:
        if not text:
            y += 1
            continue
        # 加粗合计行
        weight = "700" if kind == "sum" else "400"
        lines.append(
            f'<text x="36" y="{52 + y * 26}" font-family="Menlo, Monaco, monospace" '
            f'font-size="15" fill="{COLORS[kind]}" font-weight="{weight}">{esc(text)}</text>'
        )
        y += 1

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <rect width="{W}" height="{H}" rx="14" fill="{BG}"/>
  <!-- 终端窗口控制点 -->
  <circle cx="28" cy="24" r="6" fill="#F38BA8"/>
  <circle cx="48" cy="24" r="6" fill="#F9E2AF"/>
  <circle cx="68" cy="24" r="6" fill="#A6E3A1"/>
  <text x="{W - 24}" y="29" font-family="Menlo, Monaco, monospace" font-size="12" fill="{GRAY}" text-anchor="end">mcoptima · zsh</text>
  {''.join(lines)}
</svg>'''
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "assets", "cli_demo.svg")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(svg)
    print(f"OK {out}")


if __name__ == "__main__":
    main()
