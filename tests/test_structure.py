from pathlib import Path
import unittest
from unittest.mock import patch

import auto_unlock_helper as legacy
from picix_bot import cli
from picix_bot.api import client
from picix_bot.services import automation, catalog, packages, tasks, unlock


class StructureTests(unittest.TestCase):
    def test_data_directory_stays_at_project_root(self):
        expected = Path(__file__).resolve().parents[1] / "unlock_data"
        self.assertEqual(client.DATA_DIR, expected)

    def test_legacy_facade_exports_modular_functions(self):
        self.assertIs(legacy.api_request, client.api_request)
        self.assertIs(legacy.get_package_summary, packages.get_package_summary)
        self.assertIs(
            legacy.get_purchasable_package_state,
            catalog.get_purchasable_package_state,
        )
        self.assertIs(legacy.get_task_state, tasks.get_task_state)
        self.assertIs(legacy.unlock_movie, unlock.unlock_movie)
        self.assertIs(
            legacy.execute_points_optimization,
            automation.execute_points_optimization,
        )

    def test_cli_status_returns_failure_for_unavailable_state(self):
        unavailable = {
            "available": False,
            "auth_failed": False,
            "retryable": True,
            "error": "temporary outage",
            "items": [],
        }
        package_unavailable = {**unavailable, "packages": [], "all": [], "active": [], "remaining": 0}
        with (
            patch.object(cli, "get_task_state", return_value=unavailable),
            patch.object(cli, "get_package_summary", return_value=package_unavailable),
            patch.object(cli, "get_point_history_state", return_value=unavailable),
            patch.object(
                cli,
                "get_unlock_log",
                return_value={"unlocked_movies": [], "daily_unlocks": {}, "monthly_stats": {}},
            ),
        ):
            self.assertEqual(cli.main(["status"]), 1)


if __name__ == "__main__":
    unittest.main()
