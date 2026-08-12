from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

import auto_unlock_helper as helper


STORE_RESPONSE = {
    "success": True,
    "msg": "获取商品列表",
    "data": {
        "package": [
            {
                "id": 1,
                "name": "资源轻量包",
                "desc": "30次包，可解锁30个资源",
                "price": 450,
                "validDays": 30,
            }
        ],
        "inviteCode": [
            {
                "id": 4,
                "name": "邀请码",
                "desc": "普通邀请",
                "price": 600,
                "validDays": 3,
            }
        ],
    },
}


class ApiSafetyTests(unittest.TestCase):
    def test_live_store_shape_is_flattened_with_categories(self):
        with patch.object(helper, "api_request", return_value=STORE_RESPONSE):
            state = helper.get_purchasable_package_state()

        self.assertTrue(state["available"])
        self.assertEqual([item["id"] for item in state["items"]], [1, 4])
        self.assertEqual(state["items"][0]["_category"], "package")

    def test_lightweight_quota_is_safely_inferred_from_description(self):
        state = {
            "available": True,
            "auth_failed": False,
            "retryable": False,
            "error": "",
            "items": helper._extract_package_items(STORE_RESPONSE["data"]),
            "endpoint": "/Malls/listGoods",
            "params": None,
        }
        with patch.object(
            helper,
            "get_purchasable_package_state",
            return_value=state,
        ):
            valid, reason, package = helper.validate_purchasable_package(
                "1", 450, 30
            )

        self.assertTrue(valid, reason)
        self.assertEqual(package["quota"], 30)

    def test_auth_failure_is_not_reported_as_zero_quota(self):
        response = {
            "success": False,
            "msg": "请先登录",
            "data": [],
            "_auth_failed": True,
        }
        with patch.object(helper, "api_request", return_value=response):
            summary = helper.get_package_summary()

        self.assertFalse(summary["available"])
        self.assertTrue(summary["auth_failed"])
        self.assertIn("登录", summary["error"])

    def test_transient_failure_is_not_reported_as_zero_quota(self):
        response = {
            "success": False,
            "_request_failed": True,
            "_retryable": True,
            "_error": "Error 522: Connection timed out",
        }
        with patch.object(helper, "api_request", return_value=response):
            summary = helper.get_package_summary()

        self.assertFalse(summary["available"])
        self.assertTrue(summary["retryable"])
        self.assertIn("522", summary["error"])

    def test_real_empty_package_list_remains_available(self):
        with patch.object(
            helper,
            "api_request",
            return_value={"success": True, "data": []},
        ):
            summary = helper.get_package_summary()

        self.assertTrue(summary["available"])
        self.assertEqual(summary["remaining"], 0)


if __name__ == "__main__":
    unittest.main()
