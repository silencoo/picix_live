"""Backward-compatible facade for the modular Picix implementation.

New code should import from :mod:`picix_bot.api` and :mod:`picix_bot.services`.
This module remains so existing scripts and external callers keep working.
"""
# Re-exporting these names is the public compatibility contract of this module.
# ruff: noqa: F401

from picix_bot.api.client import (
    AUTHORIZATION, AUTHORIZATION_FILE, BASE_URL, DATA_DIR, HEADERS, LOG_FILE,
    REQUEST_TIMEOUT_SECONDS, _api_failure, _get_list_api_state, api_request,
    check_auth_valid, check_login_code, get_auth_state, load_json_file, request_login_code,
    save_json_file, update_authorization,
)
from picix_bot.api.endpoints import (
    get_all_paid_movies, get_all_paid_movies_state, get_movie_detail, get_movie_list_detail,
    get_movie_lists, get_paid_movies, get_point_history,
    get_paid_movies_state, get_point_history_state, get_recommend_movies, search_movies,
)
from picix_bot.services.automation import (
    build_live_optimization_plan, daily_unlock, ensure_package_and_unlock,
    execute_points_optimization,
)
from picix_bot.services.catalog import (
    _extract_package_items, _first_value, _infer_package_quota,
    buy_lightweight_package, find_purchasable_package,
    get_purchasable_package_state, get_purchasable_packages,
    show_purchasable_packages, validate_purchasable_package,
)
from picix_bot.services.packages import (
    get_package_info, get_package_list, get_package_state, get_package_summary,
)
from picix_bot.services.tasks import (
    accept_default_tasks, accept_task, analyze_tasks, get_task_list,
    get_task_state, should_unlock_from_list,
)
from picix_bot.services.unlock import (
    UNLOCK_LOG_FILE, find_unlocked_movie_from_list,
    find_unlocked_movie_from_recommend, get_unlock_log, pick_next_movie,
    save_unlock_record, unlock_movie, unlock_movies_batch,
)
from picix_bot.cli import main, show_status

if __name__ == "__main__":
    main()
