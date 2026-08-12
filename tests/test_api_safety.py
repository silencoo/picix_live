import unittest
from unittest.mock import patch

from picix_bot.api import client, endpoints
from picix_bot.services import catalog, packages


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
    def test_paid_movie_pagination_failure_is_not_treated_as_empty(self):
        with patch.object(
            endpoints,
            "api_request",
            return_value={
                "success": False,
                "_request_failed": True,
                "_retryable": True,
                "_error": "Error 522",
            },
        ):
            state = endpoints.get_all_paid_movies_state()

        self.assertFalse(state["available"])
        self.assertTrue(state["retryable"])
        self.assertEqual(state["items"], set())

    def test_auth_outage_is_not_reported_as_logout_or_valid(self):
        response = {
            "success": False,
            "_request_failed": True,
            "_retryable": True,
            "_error": "Error 522",
        }
        with patch.object(client, "api_request", return_value=response):
            state = client.get_auth_state()

        self.assertFalse(state["available"])
        self.assertFalse(state["auth_failed"])
        self.assertFalse(state["valid"])

    def test_auth_401_is_reported_as_logout(self):
        response = {
            "success": False,
            "_auth_failed": True,
            "msg": "请先登录",
        }
        with patch.object(client, "api_request", return_value=response):
            state = client.get_auth_state()

        self.assertFalse(state["available"])
        self.assertTrue(state["auth_failed"])

    def test_live_store_shape_is_flattened_with_categories(self):
        with patch.object(catalog, "api_request", return_value=STORE_RESPONSE):
            state = catalog.get_purchasable_package_state()

        self.assertTrue(state["available"])
        self.assertEqual([item["id"] for item in state["items"]], [1, 4])
        self.assertEqual(state["items"][0]["_category"], "package")

    def test_lightweight_quota_is_safely_inferred_from_description(self):
        state = {
            "available": True,
            "auth_failed": False,
            "retryable": False,
            "error": "",
            "items": catalog._extract_package_items(STORE_RESPONSE["data"]),
            "endpoint": "/Malls/listGoods",
            "params": None,
        }
        with patch.object(
            catalog,
            "get_purchasable_package_state",
            return_value=state,
        ):
            valid, reason, package = catalog.validate_purchasable_package(
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
        with patch.object(packages, "api_request", return_value=response):
            summary = packages.get_package_summary()

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
        with patch.object(packages, "api_request", return_value=response):
            summary = packages.get_package_summary()

        self.assertFalse(summary["available"])
        self.assertTrue(summary["retryable"])
        self.assertIn("522", summary["error"])

    def test_real_empty_package_list_remains_available(self):
        with patch.object(
            packages,
            "api_request",
            return_value={"success": True, "data": []},
        ):
            summary = packages.get_package_summary()

        self.assertTrue(summary["available"])
        self.assertEqual(summary["remaining"], 0)


if __name__ == "__main__":
    unittest.main()
