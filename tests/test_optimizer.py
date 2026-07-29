from datetime import datetime, timedelta
import unittest
from zoneinfo import ZoneInfo

from picix_bot.optimizer import (
    build_optimization_plan,
    summarize_monthly_spend,
    summarize_packages,
)


TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 9, 0, tzinfo=TZ)


def task(current, target, *, finished=False, days=30):
    return {
        "current": current,
        "target": target,
        "is_finish": finished,
        "end_at": int((NOW + timedelta(days=days)).timestamp()),
    }


def history(points=1350, spend=0):
    records = [
        {
            "timestamp": int(NOW.timestamp()),
            "type": "INC",
            "value": 15,
            "desc": "完成任务：每日解锁",
            "totalPoints": points,
        }
    ]
    if spend:
        records.append(
            {
                "timestamp": int(NOW.timestamp()),
                "type": "DEC",
                "value": spend,
                "desc": "解锁电影：测试影片",
                "totalPoints": points - spend,
            }
        )
    return records


class OptimizerTests(unittest.TestCase):
    def test_minimum_penalty_is_not_counted_as_spend(self):
        records = [
            {
                "timestamp": int(NOW.timestamp()),
                "type": "DEC",
                "value": 430,
                "desc": "最低消费450 - 不足部分扣减",
                "totalPoints": 1000,
            },
            {
                "timestamp": int(NOW.timestamp()),
                "type": "DEC",
                "value": 20,
                "desc": "解锁电影：测试",
                "totalPoints": 1430,
            },
        ]
        points, spend, penalty = summarize_monthly_spend(records, now=NOW)
        self.assertEqual(points, 1000)
        self.assertEqual(spend, 20)
        self.assertEqual(penalty, 430)

    def test_expired_and_exhausted_packages_are_ignored(self):
        packages = [
            {"total": 30, "used": 10, "expiredAt": int((NOW + timedelta(days=2)).timestamp())},
            {"total": 30, "used": 30, "expiredAt": int((NOW + timedelta(days=2)).timestamp())},
            {"total": 30, "used": 0, "expiredAt": int((NOW - timedelta(days=1)).timestamp())},
        ]
        remaining, active = summarize_packages(packages, now=NOW)
        self.assertEqual(remaining, 20)
        self.assertEqual(len(active), 1)

    def test_new_cycle_buys_one_package_and_catches_up_twenty(self):
        tasks = {
            "D_UL_1": task(0, 1),
            "M_UL_50": task(0, 50),
            "M_UL_ML_20": task(0, 20),
        }
        plan = build_optimization_plan(
            history=history(),
            packages=[],
            tasks=tasks,
            now=NOW,
        )
        self.assertEqual(plan.daily_unlocks, 1)
        self.assertEqual(plan.catch_up_unlocks, 20)
        self.assertEqual(plan.unlocks_now, 21)
        self.assertEqual(plan.packages_to_buy, 1)

    def test_existing_quota_is_used_before_buying_early_in_month(self):
        tasks = {
            "D_UL_1": task(0, 1),
            "M_UL_50": task(0, 50),
            "M_UL_ML_20": task(0, 20),
        }
        packages = [
            {"total": 30, "used": 0, "expiredAt": int((NOW + timedelta(days=10)).timestamp())}
        ]
        plan = build_optimization_plan(
            history=history(),
            packages=packages,
            tasks=tasks,
            now=NOW,
        )
        self.assertEqual(plan.unlocks_now, 21)
        self.assertEqual(plan.packages_to_buy, 0)

    def test_late_month_purchase_replaces_minimum_spend_penalty(self):
        late = NOW.replace(day=27)
        tasks = {
            "D_UL_1": {"current": 1, "target": 1, "is_finish": True},
            "M_UL_50": {"current": 50, "target": 50, "is_finish": True},
            "M_UL_ML_20": {"current": 20, "target": 20, "is_finish": True},
        }
        plan = build_optimization_plan(
            history=history(),
            packages=[{"total": 30, "used": 0}],
            tasks=tasks,
            now=late,
        )
        self.assertEqual(plan.unlocks_now, 0)
        self.assertEqual(plan.packages_to_buy, 1)
        self.assertIn("本月合格消费还差 450 分", plan.purchase_reasons)

    def test_partial_direct_spend_still_requires_the_threshold(self):
        late = NOW.replace(day=27)
        plan = build_optimization_plan(
            history=history(points=900, spend=20),
            packages=[],
            tasks={},
            now=late,
        )
        self.assertEqual(plan.spend_shortfall, 430)
        self.assertEqual(plan.packages_to_buy, 1)

    def test_low_balance_blocks_purchase(self):
        tasks = {
            "D_UL_1": task(0, 1),
            "M_UL_50": task(0, 50),
            "M_UL_ML_20": task(0, 20),
        }
        plan = build_optimization_plan(
            history=history(points=449),
            packages=[],
            tasks=tasks,
            now=NOW,
        )
        self.assertEqual(plan.packages_to_buy, 0)
        self.assertTrue(any("积分不足" in reason for reason in plan.blocked_reasons))

    def test_exact_package_balance_can_start_the_strategy(self):
        tasks = {
            "D_UL_1": task(0, 1),
            "M_UL_50": task(0, 50),
            "M_UL_ML_20": task(0, 20),
        }
        plan = build_optimization_plan(
            history=history(points=450),
            packages=[],
            tasks=tasks,
            now=NOW,
        )
        self.assertEqual(plan.packages_to_buy, 1)

    def test_urgent_fifty_unlocks_can_request_two_packages(self):
        urgent_tasks = {
            "D_UL_1": {
                "current": 1,
                "target": 1,
                "is_finish": True,
            },
            "M_UL_50": {
                "current": 0,
                "target": 50,
                "is_finish": False,
                "end_at": int((NOW + timedelta(hours=2)).timestamp()),
            },
            "M_UL_ML_20": {
                "current": 0,
                "target": 20,
                "is_finish": False,
                "end_at": int((NOW + timedelta(hours=2)).timestamp()),
            },
        }
        plan = build_optimization_plan(
            history=history(points=900),
            packages=[],
            tasks=urgent_tasks,
            now=NOW,
        )
        self.assertEqual(plan.unlocks_now, 50)
        self.assertEqual(plan.packages_to_buy, 2)

    def test_reserve_can_block_an_otherwise_affordable_purchase(self):
        late = NOW.replace(day=27)
        plan = build_optimization_plan(
            history=history(points=500),
            packages=[],
            tasks={},
            now=late,
            points_reserve=100,
        )
        self.assertEqual(plan.packages_to_buy, 0)
        self.assertTrue(any("积分不足" in reason for reason in plan.blocked_reasons))

    def test_completed_monthly_spend_needs_no_fallback_purchase(self):
        late = NOW.replace(day=27)
        plan = build_optimization_plan(
            history=history(points=900, spend=450),
            packages=[],
            tasks={},
            now=late,
        )
        self.assertEqual(plan.spend_shortfall, 0)
        self.assertEqual(plan.packages_to_buy, 0)

    def test_rolling_spend_cycle_crosses_calendar_month_boundary(self):
        penalty_time = datetime(2026, 1, 22, 16, 0, tzinfo=TZ)
        purchase_time = datetime(2026, 1, 31, 12, 0, tzinfo=TZ)
        now = datetime(2026, 2, 1, 9, 0, tzinfo=TZ)
        records = [
            {
                "timestamp": int(purchase_time.timestamp()),
                "type": "DEC",
                "value": 20,
                "desc": "解锁电影：跨月测试",
                "totalPoints": 1000,
            },
            {
                "timestamp": int(penalty_time.timestamp()),
                "type": "DEC",
                "value": 450,
                "desc": "最低消费450 - 不足部分扣减",
                "totalPoints": 1020,
            },
        ]
        plan = build_optimization_plan(
            history=records,
            packages=[],
            tasks={},
            now=now,
        )
        self.assertEqual(plan.monthly_spend, 20)
        self.assertEqual(plan.spend_shortfall, 430)
        self.assertEqual(plan.spend_cycle_source, "penalty_history")
        self.assertEqual(plan.packages_to_buy, 0)

    def test_rolling_cycle_uses_its_own_day_twenty_five(self):
        penalty_time = datetime(2026, 1, 22, 16, 0, tzinfo=TZ)
        now = datetime(2026, 2, 16, 17, 0, tzinfo=TZ)
        records = [
            {
                "timestamp": int(now.timestamp()),
                "type": "INC",
                "value": 15,
                "desc": "完成任务：每日解锁",
                "totalPoints": 900,
            },
            {
                "timestamp": int(penalty_time.timestamp()),
                "type": "DEC",
                "value": 450,
                "desc": "最低消费450 - 不足部分扣减",
                "totalPoints": 885,
            },
        ]
        plan = build_optimization_plan(
            history=records,
            packages=[],
            tasks={},
            now=now,
        )
        self.assertGreaterEqual(plan.spend_cycle_day, 25)
        self.assertEqual(plan.packages_to_buy, 1)

    def test_carry_over_quota_avoids_fixed_two_pack_waste(self):
        tasks = {
            "D_UL_1": task(0, 1),
            "M_UL_50": task(40, 50, days=10),
            "M_UL_ML_20": task(20, 20, finished=True, days=10),
        }
        packages = [{"total": 30, "used": 20}]
        plan = build_optimization_plan(
            history=history(points=1000, spend=450),
            packages=packages,
            tasks=tasks,
            now=NOW,
        )
        self.assertEqual(plan.unlocks_now, 1)
        self.assertEqual(plan.packages_to_buy, 0)


if __name__ == "__main__":
    unittest.main()
