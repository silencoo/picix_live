"""Unified command-line entry point for Picix automation."""
from __future__ import annotations

import argparse
from datetime import datetime
import json

from picix_bot.api.client import get_auth_state
from picix_bot.api.endpoints import get_point_history_state
from picix_bot.services.automation import (
    build_live_optimization_plan,
    daily_unlock,
    ensure_package_and_unlock,
    execute_points_optimization,
)
from picix_bot.services.catalog import show_purchasable_packages
from picix_bot.services.packages import get_package_summary
from picix_bot.services.tasks import analyze_tasks, get_task_state
from picix_bot.services.unlock import get_unlock_log
from picix_bot.settings import settings


def _optimizer_options() -> dict:
    return {
        "timezone_name": settings.timezone,
        "minimum_spend": settings.minimum_monthly_spend,
        "package_price": settings.package_price,
        "package_quota": settings.package_quota,
        "spend_cycle_days": settings.spend_cycle_days,
        "spend_trigger_day": settings.spend_trigger_day,
        "points_reserve": settings.points_reserve,
        "max_auto_purchases": settings.max_auto_purchases,
        "max_auto_unlocks": settings.max_auto_unlocks,
    }


def show_status() -> bool:
    """Print a fail-closed status snapshot for operators."""
    task_state = get_task_state()
    package_summary = get_package_summary()
    history_state = get_point_history_state()

    print("=" * 60)
    print("Picix 当前状态")
    print("=" * 60)

    unavailable = []
    for label, state in (
        ("任务", task_state),
        ("资源包", package_summary),
        ("积分", history_state),
    ):
        if not state["available"]:
            unavailable.append(f"{label}: {state['error']}")

    if unavailable:
        print("\n⚠️ 状态不完整（不会按 0 处理）:")
        for error in unavailable:
            print(f"  - {error}")

    if task_state["available"]:
        tasks = analyze_tasks(task_state["items"]) or {}
        print("\n任务进度:")
        if not tasks:
            print("  当前没有任务")
        for info in tasks.values():
            status = "✓" if info["is_finish"] else "…"
            print(
                f"  {status} {info['name']}: "
                f"{info['current']}/{info['target']}，奖励 {info['point']} 分"
            )

    if package_summary["available"]:
        print("\n资源包:")
        print(f"  有效包: {len(package_summary['active'])} 个")
        print(f"  总剩余: {package_summary['remaining']} 次")

    if history_state["available"]:
        history = history_state["items"]
        points = history[0].get("totalPoints") if history else None
        print(f"\n当前积分: {points if points is not None else '无记录'}")

    log = get_unlock_log()
    month = datetime.now().strftime("%Y-%m")
    stats = log["monthly_stats"].get(
        month,
        {"total": 0, "from_list": 0},
    )
    print(f"\n本地记录 ({month}):")
    print(f"  总解锁: {stats['total']}")
    print(f"  片单解锁: {stats['from_list']}")
    return not unavailable


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Picix 统一控制台")
    parser.add_argument(
        "action",
        choices=[
            "bot",
            "status",
            "unlock",
            "plan",
            "optimize",
            "auto-buy",
            "packages",
            "token",
        ],
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.action == "bot":
        from picix_bot.app import main as bot_main

        bot_main()
        return 0
    if args.action == "status":
        return 0 if show_status() else 1
    if args.action == "unlock":
        return 0 if daily_unlock() else 1
    if args.action == "packages":
        show_purchasable_packages()
        return 0
    if args.action == "token":
        state = get_auth_state()
        if state["available"]:
            print("✓ Picix 登录有效")
            return 0
        if state["auth_failed"]:
            print("✗ Picix 登录已失效，请执行 /reauth")
        else:
            print(f"⚠️ 暂时无法检查登录状态：{state['error']}")
        return 1

    options = _optimizer_options()
    if args.action == "plan":
        plan = build_live_optimization_plan(**options)
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.action == "optimize":
        report = execute_points_optimization(
            **options,
            allow_purchase=settings.auto_purchase,
            package_good_id=settings.package_good_id,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["success"] else 1
    if args.action == "auto-buy":
        return 0 if ensure_package_and_unlock() else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
