"""solver 单元测试 - 不依赖网络, 用固定数据验证算法正确性."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skill", "scripts"))

from solver import Constraints, FoodItem, Solution, solve, explain  # noqa: E402


def make_item(code, name, price, kcal, protein, category="汉堡", max_qty=1):
    return FoodItem(
        code=code, name=name, price=price, kcal=kcal,
        protein=protein, category=category, max_qty=max_qty,
    )


def sample_menu():
    return [
        make_item("A1", "巨无霸", 24.0, 513, 27, "汉堡"),
        make_item("A2", "麦乐鸡5块", 13.5, 213, 12, "小食"),
        make_item("A3", "中薯条", 12.0, 289, 4, "小食"),
        make_item("A4", "可乐中杯", 9.5, 147, 0, "饮品", max_qty=3),
        make_item("A5", "麦麦脆汁鸡", 19.9, 290, 20, "炸鸡"),
        make_item("A6", "圆筒冰淇淋", 5.0, 93, 2, "甜品", max_qty=3),
    ]


def test_basic_feasibility():
    sols = solve(sample_menu(), Constraints(budget=30, kcal_cap=800, protein_floor=25), top_k=3)
    assert len(sols) >= 1
    for s in sols:
        assert s.total_price <= 30 + 1e-6
        assert s.total_kcal <= 800
        assert s.total_protein >= 25


def test_budget_respected():
    sols = solve(sample_menu(), Constraints(budget=15, kcal_cap=600, protein_floor=0), top_k=3)
    for s in sols:
        assert s.total_price <= 15 + 1e-6


def test_kcal_respected():
    sols = solve(sample_menu(), Constraints(budget=100, kcal_cap=300, protein_floor=0), top_k=3)
    for s in sols:
        assert s.total_kcal <= 300


def test_infeasible_raises():
    try:
        solve(sample_menu(), Constraints(budget=4, kcal_cap=800, protein_floor=0), top_k=1)
        assert False, "should raise"
    except ValueError:
        pass


def test_protein_floor_unreachable():
    try:
        solve(sample_menu(), Constraints(budget=50, kcal_cap=800, protein_floor=1000), top_k=1)
        assert False, "should raise"
    except ValueError:
        pass


def test_multi_qty():
    sols = solve(sample_menu(), Constraints(budget=20, kcal_cap=500, protein_floor=0), top_k=1)
    assert sols[0].total_price <= 20


def test_dedup_solutions():
    sols = solve(sample_menu(), Constraints(budget=40, kcal_cap=800, protein_floor=0), top_k=3)
    names = [s.name for s in sols]
    assert len(set(names)) == len(names), "解不应重复"


def test_explain_output():
    sols = solve(sample_menu(), Constraints(budget=30, kcal_cap=800, protein_floor=25), top_k=1)
    text = explain(sols[0], Constraints(budget=30, kcal_cap=800, protein_floor=25))
    assert "kcal" in text and "¥" in text


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
        print(f"PASS {fn.__name__}")
    print("\nAll tests passed.")
