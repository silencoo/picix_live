from datetime import datetime, timedelta
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from picix_bot.services import automation as helper


TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime.now(TZ)


def active_tasks():
    end_at = int((NOW + timedelta(days=30)).timestamp())
    return {
        "D_UL_1": {
            "current": 0,
            "target": 1,
            "is_finish": False,
            "end_at": int((NOW + timedelta(hours=10)).timestamp()),
        },
        "M_UL_50": {
            "current": 0,
            "target": 50,
            "is_finish": False,
            "end_at": end_at,
        },
        "M_UL_ML_20": {
            "current": 0,
            "target": 20,
            "is_finish": False,
            "end_at": end_at,
        },
    }


HISTORY = [
    {
        "timestamp": int(NOW.timestamp()),
        "type": "INC",
        "value": 15,
        "desc": "完成任务：每日解锁",
        "totalPoints": 900,
    }
]


def available_state(items, key="items"):
    return {
        "available": True,
        "auth_failed": False,
        "retryable": False,
        "error": "",
        key: items,
    }


class OptimizerExecutionTests(unittest.TestCase):
    def test_purchase_is_verified_before_unlocking(self):
        package = {
            "total": 30,
            "used": 0,
            "expiredAt": int((NOW + timedelta(days=30)).timestamp()),
        }
        fake_unlock_result = {
            "requested": 21,
            "attempted": 21,
            "successes": [{"movie_id": index} for index in range(21)],
            "failure": None,
            "available_before": 30,
        }
        with (
            patch.object(
                helper,
                "get_task_state",
                return_value=available_state([]),
            ),
            patch.object(
                helper,
                "get_point_history_state",
                return_value=available_state(HISTORY),
            ),
            patch.object(
                helper,
                "get_package_state",
                return_value=available_state([], "packages"),
            ),
            patch.object(
                helper,
                "get_package_summary",
                return_value={
                    **available_state([package], "all"),
                    "remaining": 30,
                    "active": [],
                },
            ),
            patch.object(helper, "accept_default_tasks", return_value={}),
            patch.object(helper, "analyze_tasks", return_value=active_tasks()),
            patch.object(
                helper,
                "validate_purchasable_package",
                return_value=(
                    True,
                    "",
                    {"name": "资源轻量包", "good_id": "1"},
                ),
            ),
            patch.object(
                helper,
                "buy_lightweight_package",
                return_value=(True, "购买成功"),
            ) as buy,
            patch.object(
                helper,
                "unlock_movies_batch",
                return_value=fake_unlock_result,
            ) as unlock,
            patch.object(helper.time, "sleep"),
        ):
            report = helper.execute_points_optimization()

        self.assertTrue(report["success"])
        buy.assert_called_once_with("1")
        unlock.assert_called_once_with(21, prefer_list=True)

    def test_changed_shop_parameters_stop_before_purchase(self):
        with (
            patch.object(
                helper,
                "get_task_state",
                return_value=available_state([]),
            ),
            patch.object(
                helper,
                "get_point_history_state",
                return_value=available_state(HISTORY),
            ),
            patch.object(
                helper,
                "get_package_state",
                return_value=available_state([], "packages"),
            ),
            patch.object(helper, "accept_default_tasks", return_value={}),
            patch.object(helper, "analyze_tasks", return_value=active_tasks()),
            patch.object(
                helper,
                "validate_purchasable_package",
                return_value=(False, "轻量包价格已变化", None),
            ),
            patch.object(helper, "buy_lightweight_package") as buy,
            patch.object(helper, "unlock_movies_batch") as unlock,
        ):
            report = helper.execute_points_optimization()

        self.assertFalse(report["success"])
        self.assertIn("轻量包价格已变化", report["messages"])
        buy.assert_not_called()
        unlock.assert_not_called()

    def test_unavailable_package_state_never_purchases(self):
        unavailable = {
            "available": False,
            "auth_failed": False,
            "retryable": True,
            "error": "Error 522: Connection timed out",
            "packages": [],
        }
        with (
            patch.object(helper, "get_task_state", return_value=available_state([])),
            patch.object(
                helper,
                "get_point_history_state",
                return_value=available_state(HISTORY),
            ),
            patch.object(helper, "get_package_state", return_value=unavailable),
            patch.object(helper, "buy_lightweight_package") as buy,
            patch.object(helper, "unlock_movies_batch") as unlock,
        ):
            report = helper.execute_points_optimization()

        self.assertFalse(report["success"])
        self.assertIn("状态不确定，本次不会购买或解锁", report["messages"])
        buy.assert_not_called()
        unlock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
