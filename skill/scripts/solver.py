"""McOptima 核心求解器 - 多约束 0/1 背包动态规划。

问题形式化:
    maximize   Σ u_i · x_i              (满足感总分)
    subject to Σ price_i · x_i ≤ B      (预算上限, ¥1 粒度)
               Σ cal_i · x_i ≤ C        (热量上限, 10kcal 粒度)
               Σ protein_i · x_i ≥ P    (蛋白下限, 硬约束, 前置过滤)
               Σ sodium_i · x_i ≤ Na    (钠上限, 可选)
    x_i ∈ {0, 1, ..., q_i}              (部分餐品可复数份, 默认 1)

满足感评分 u_i = w1·蛋白质密度 + w2·性价比 + w3·口味偏好 + w4·品类去重惩罚
所有营养数据来自麦当劳官方 MCP list-nutrition-foods, 价格来自 query-meals / calculate-price。

输出仅供参考, 不构成医疗、营养或其他专业建议。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CAL_GRAN = 10          # 热量粒度: 10 kcal
PRICE_GRAN = 1         # 预算粒度: ¥1
MAX_ITEMS_PER_SOLUTION = 12   # 单方案最大餐品数(防"12 杯玉米杯"式怪解)


@dataclass
class FoodItem:
    code: str
    name: str
    price: float            # 当前门店价格(券前)
    kcal: int               # 能量 kcal
    protein: float          # 蛋白质 g
    fat: float = 0.0
    carb: float = 0.0
    sodium: int = 0         # 钠 mg
    category: str = ""      # 菜单分类
    tags: list[str] = field(default_factory=list)
    max_qty: int = 1        # 可购份数上限(饮品/小食可>1)

    @property
    def protein_density(self) -> float:
        """每百元蛋白质克数 - 健身视角核心指标."""
        return self.protein / self.price * 100 if self.price > 0 else 0.0

    @property
    def kcal_per_yuan(self) -> float:
        """每元热量 - 省钱吃饱视角."""
        return self.kcal / self.price if self.price > 0 else 0.0

    @property
    def value_density(self) -> float:
        """每元满足感密度(默认评分)."""
        return self.base_score / self.price if self.price > 0 else 0.0

    @property
    def base_score(self) -> float:
        """满足感基础分: 蛋白密度为主 + 品类调整。设计原则:
        1. 蛋白质密度是核心 (健身/性价比视角)
        2. 甜品/饮品/小食适度降权 (正餐满足感优先, 防止 DP 用低价甜品刷分)
        3. 同一单品复数份强衰减在 expand 层处理 (×0.9^n)
        """
        s = self.protein_density * 2.0
        if self.category in ("小食甜品/其他", "饮品", "麦咖啡™", "甜品"):
            s *= 0.5
        if any(k in self.category for k in ("汉堡", "卷", "套餐", "单人餐", "炸鸡", "拼盘")):
            s *= 1.1
        return round(s, 4)


@dataclass
class Constraints:
    budget: float = 30.0        # 预算上限 ¥
    kcal_cap: int = 800         # 热量上限 kcal
    protein_floor: float = 0.0  # 蛋白质下限 g
    sodium_cap: int | None = None  # 钠上限 mg(可选)
    forbid_categories: set[str] = field(default_factory=set)
    exclude_codes: set[str] = field(default_factory=set)


@dataclass
class Solution:
    items: list[tuple[FoodItem, int]]   # (餐品, 份数)
    total_price: float
    total_kcal: int
    total_protein: float
    score: float

    @property
    def name(self) -> str:
        return " + ".join(f"{it.name}×{q}" if q > 1 else it.name for it, q in self.items)


def _filter_items(items: list[FoodItem], c: Constraints) -> list[FoodItem]:
    """硬约束前置过滤: 单品预算内、不超热量、蛋白下限可达、分类黑白名单."""
    kept = []
    protein_reachable = 0.0
    for it in items:
        if it.code in c.exclude_codes:
            continue
        if it.category in c.forbid_categories:
            continue
        if it.price > c.budget or it.kcal > c.kcal_cap:
            continue
        kept.append(it)
        protein_reachable += it.protein * it.max_qty
    if c.protein_floor > 0 and protein_reachable < c.protein_floor:
        raise ValueError(
            f"无可行解: 全菜单蛋白质上限 {protein_reachable:.0f}g < 要求 {c.protein_floor:.0f}g, 请降低蛋白下限"
        )
    return kept


def _solve_once(
    expanded: list[tuple[FoodItem, int, float]],
    banned: set[int],
    B: int,
    C: int,
    P: int = 0,
) -> list[int] | None:
    """带禁用条目的一次 0/1 背包求解, 返回 picked 条目索引列表 (无解返回 None)。

    三维 DP: (预算, 热量, 蛋白累计)。蛋白作为第三维约束 (蛋白下限 P, 单位 g 取整)。
    choice[i][b][c][p] 记录第 i 层是否选取, 回溯按层走保证正确性。
    维度: n层 × B × C × P。真实菜单 n≈200, B≈150, C≈120, P≈60 → 内存过大时
    自动降级为二维 DP + 蛋白后验校验(多次重解)。
    """
    NEG = float("-inf")

    def cal_cell(kcal: int) -> int:
        return -(-kcal // CAL_GRAN)

    if P > 0 and B * C * (P + 1) * len(expanded) > 400_000_000:
        # 维度过大: 降级为二维 (蛋白后验校验由外层 banned 迭代兜底)
        P = 0

    if P > 0:
        # 三维 DP (蛋白维, 语义: dp[b][c][p] = 蛋白≥p 时的最优分)
        prev_dp = [[[NEG] * (P + 1) for _ in range(C + 1)] for _ in range(B + 1)]
        for b in range(B + 1):
            for cc in range(C + 1):
                prev_dp[b][cc][0] = 0.0  # 只有 p=0 层免费; p>0 需真实蛋白填充
        choice: list = []
        for idx, (it, k, decay) in enumerate(expanded):
            if idx in banned:
                choice.append(None)
                continue
            pb = int(round(it.price / PRICE_GRAN))
            pc = cal_cell(it.kcal)
            pp = max(1, int(it.protein)) if it.protein > 0 else 0
            score = it.base_score * decay
            cur = [[[NEG] * (P + 1) for _ in range(C + 1)] for _ in range(B + 1)]
            take = [[[False] * (P + 1) for _ in range(C + 1)] for _ in range(B + 1)]
            for b in range(B + 1):
                for cc in range(C + 1):
                    for p in range(P + 1):
                        if prev_dp[b][cc][p] > NEG:
                            cur[b][cc][p] = prev_dp[b][cc][p]
                        if b >= pb and cc >= pc:
                            src_p = max(0, p - pp)
                            cand = prev_dp[b - pb][cc - pc][src_p]
                            if cand > NEG and (cur[b][cc][p] == NEG or cand + score > cur[b][cc][p]):
                                cur[b][cc][p] = cand + score
                                take[b][cc][p] = True
            choice.append(take)
            prev_dp = cur
        if prev_dp[B][C][P] == NEG:
            return None
        picked: list[int] = []
        b, cc, p = B, C, P
        for i in range(len(expanded) - 1, -1, -1):
            ch = choice[i]
            if ch is not None and ch[b][cc][p]:
                picked.append(i)
                it, _, _ = expanded[i]
                b -= int(round(it.price / PRICE_GRAN))
                cc -= cal_cell(it.kcal)
                p = max(0, p - (max(1, int(it.protein)) if it.protein > 0 else 0))
        picked.reverse()
        return picked or None

    # 二维 DP (无蛋白维)
    prev_dp2: list[list[float]] = [[0.0] * (C + 1) for _ in range(B + 1)]
    choice2: list = []
    for idx, (it, k, decay) in enumerate(expanded):
        if idx in banned:
            choice2.append(None)
            continue
        pb = int(round(it.price / PRICE_GRAN))
        pc = cal_cell(it.kcal)
        score = it.base_score * decay
        cur = [[NEG] * (C + 1) for _ in range(B + 1)]
        take = [[False] * (C + 1) for _ in range(B + 1)]
        for b in range(B + 1):
            for cc in range(C + 1):
                if prev_dp2[b][cc] > NEG:
                    cur[b][cc] = prev_dp2[b][cc]
                if b >= pb and cc >= pc:
                    cand = prev_dp2[b - pb][cc - pc]
                    if cand > NEG and (cur[b][cc] == NEG or cand + score > cur[b][cc]):
                        cur[b][cc] = cand + score
                        take[b][cc] = True
        choice2.append(take)
        prev_dp2 = cur
    if prev_dp2[B][C] == NEG:
        return None
    picked = []
    b, cc = B, C
    for i in range(len(expanded) - 1, -1, -1):
        ch = choice2[i]
        if ch is not None and ch[b][cc]:
            picked.append(i)
            it, _, _ = expanded[i]
            b -= int(round(it.price / PRICE_GRAN))
            cc -= cal_cell(it.kcal)
    picked.reverse()
    return picked or None


def solve(items: list[FoodItem], c: Constraints, top_k: int = 3) -> list[Solution]:
    """多约束 0/1 背包(份数≤max_qty 展开为多重背包的 0/1 展开), 输出 top-k 方案."""
    pool = _filter_items(items, c)
    if not pool:
        raise ValueError("无可行解: 过滤后菜单为空, 请放宽预算/热量/分类限制")

    # 展开复数份为虚拟条目 (同一单品第2份视为新条目, 满足感乘 0.9 衰减防刷分)
    expanded: list[tuple[FoodItem, int, float]] = []
    for it in pool:
        for k in range(1, it.max_qty + 1):
            expanded.append((it, k, 1.0 if k == 1 else 0.9 ** (k - 1)))

    B = int(c.budget / PRICE_GRAN)     # 预算格数
    C = int(c.kcal_cap / CAL_GRAN)     # 热量格数
    P = int(c.protein_floor)           # 蛋白格数 (g 整数)

    results: list[Solution] = []
    banned: set[int] = set()

    for _ in range(top_k):
        picked = _solve_once(expanded, banned, B, C, P)
        if not picked:
            break
        chosen = [expanded[i] for i in picked]
        total_protein = sum(it.protein for it, _, _ in chosen)
        total_sodium = sum(it.sodium for it, _, _ in chosen)
        # 汇总份数 (同 code 多份合并)
        by_code: dict[str, tuple[FoodItem, int]] = {}
        for it, _, _ in chosen:
            by_code[it.code] = (it, by_code.get(it.code, (it, 0))[1] + 1)
        sol_items = list(by_code.values())
        sol = Solution(
            items=sol_items,
            total_price=sum(it.price * q for it, q in sol_items),
            total_kcal=sum(it.kcal * q for it, q in sol_items),
            total_protein=total_protein,
            score=round(sum(it.base_score * decay for it, _, decay in chosen), 2),
        )
        # 约束二次校验 (DP 粒度取整 + 蛋白/钠/条目数的兜底)
        ok = (
            sol.total_price <= c.budget + 1e-6
            and sol.total_kcal <= c.kcal_cap
            and (c.protein_floor <= 0 or total_protein >= c.protein_floor)
            and (c.sodium_cap is None or total_sodium <= c.sodium_cap)
            and len(picked) <= MAX_ITEMS_PER_SOLUTION
        )
        if not ok:
            banned.update(picked)
            continue
        results.append(sol)
        # 次优解: 禁用本解条目后重解
        banned.update(picked)

    if not results:
        raise ValueError("无可行解: 请放宽约束(预算/热量/蛋白/钠)")
    return results


def explain(sol: Solution, c: Constraints) -> str:
    """生成人类可读的方案说明(含对比数据)."""
    lines = [
        f"最优组合: {sol.name}",
        f"总价 ¥{sol.total_price:.1f} / 预算 ¥{c.budget:.0f} (剩余 ¥{c.budget - sol.total_price:.1f})",
        f"总热量 {sol.total_kcal} kcal / 上限 {c.kcal_cap} kcal",
        f"蛋白质 {sol.total_protein:.1f} g",
    ]
    if c.protein_floor > 0:
        lines[3] += f" / 下限 {c.protein_floor:.0f} g"
    lines.append(f"满足感评分 {sol.score}")
    return "\n".join(lines)
