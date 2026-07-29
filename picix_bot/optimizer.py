"""Pure planning logic for maximizing Picix task points.

This module does not call the network.  Keeping the calculations pure makes it
possible to test purchase and unlock decisions without risking real points.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import math
from typing import Any
from zoneinfo import ZoneInfo


MINIMUM_SPEND_PENALTY_MARKERS = ("最低消费", "不足部分扣减", "保号")
QUALIFYING_SPEND_MARKERS = ("购买商品", "解锁电影", "购买影片", "购买资源")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _task_remaining(task: dict[str, Any] | None) -> int:
    if not task or task.get("is_finish"):
        return 0
    return max(0, _as_int(task.get("target")) - _as_int(task.get("current")))


def _safe_daily_slots(
    task: dict[str, Any] | None,
    *,
    now: datetime,
    daily_pending: bool,
    fallback: int,
) -> int:
    """Estimate reliable one-per-day opportunities before a task expires.

    Whole 24-hour blocks are intentionally used instead of calendar dates so
    the plan does not depend on an unlock during the final partial day.
    """

    if not task or task.get("is_finish"):
        return 0
    end_at = _as_int(task.get("end_at"))
    if end_at <= 0:
        return max(1 if daily_pending else 0, fallback)
    seconds_left = end_at - int(now.timestamp())
    if seconds_left <= 0:
        return 1 if daily_pending else 0
    whole_days = seconds_left // 86_400
    return max(1 if daily_pending else 0, whole_days)


def summarize_monthly_spend(
    history: list[dict[str, Any]],
    *,
    now: datetime,
    cycle_days: int = 30,
) -> tuple[int | None, int, int]:
    """Return points and spend in the active minimum-spend cycle."""

    current_points = None
    if history:
        current_points = _as_int(history[0].get("totalPoints"))

    cycle_start, cycle_end, _ = resolve_spend_cycle(
        history,
        now=now,
        cycle_days=cycle_days,
    )
    qualifying = 0
    penalties = 0
    for record in history:
        timestamp = _as_int(record.get("timestamp"))
        if timestamp <= 0:
            continue
        record_time = datetime.fromtimestamp(timestamp, tz=now.tzinfo)
        if not cycle_start <= record_time < cycle_end:
            continue
        if str(record.get("type", "")).upper() != "DEC":
            continue

        value = max(0, _as_int(record.get("value")))
        description = str(record.get("desc", ""))
        if any(marker in description for marker in MINIMUM_SPEND_PENALTY_MARKERS):
            penalties += value
        elif any(marker in description for marker in QUALIFYING_SPEND_MARKERS):
            qualifying += value

    return current_points, qualifying, penalties


def resolve_spend_cycle(
    history: list[dict[str, Any]],
    *,
    now: datetime,
    cycle_days: int = 30,
) -> tuple[datetime, datetime, str]:
    """Resolve the rolling spend cycle from penalty history.

    Captured account history shows the deduction recurring roughly every 30
    days rather than on calendar-month boundaries.  The latest penalty is the
    strongest available anchor.  New accounts without an anchor fall back to
    the natural month until the first deduction is observed.
    """

    duration = timedelta(days=max(1, cycle_days))
    penalty_times: list[datetime] = []
    for record in history:
        if str(record.get("type", "")).upper() != "DEC":
            continue
        description = str(record.get("desc", ""))
        if not any(
            marker in description for marker in MINIMUM_SPEND_PENALTY_MARKERS
        ):
            continue
        timestamp = _as_int(record.get("timestamp"))
        if timestamp > 0 and timestamp <= int(now.timestamp()):
            penalty_times.append(datetime.fromtimestamp(timestamp, tz=now.tzinfo))

    if penalty_times:
        anchor = max(penalty_times)
        cycles_elapsed = max(0, (now - anchor) // duration)
        start = anchor + cycles_elapsed * duration
        return start, start + duration, "penalty_history"

    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end, "calendar_fallback"


def summarize_packages(
    packages: list[dict[str, Any]],
    *,
    now: datetime,
) -> tuple[int, list[dict[str, Any]]]:
    """Return total usable quota and normalized active package details."""

    active: list[dict[str, Any]] = []
    now_timestamp = int(now.timestamp())
    for package in packages:
        total = max(0, _as_int(package.get("total")))
        used = max(0, _as_int(package.get("used")))
        remaining = max(0, total - used)
        expired_at = _as_int(package.get("expiredAt"))
        if remaining <= 0 or (expired_at > 0 and expired_at <= now_timestamp):
            continue
        active.append(
            {
                "total": total,
                "used": used,
                "remaining": remaining,
                "expired_at": expired_at or None,
                "raw": package,
            }
        )

    active.sort(key=lambda item: item["expired_at"] or 2**63)
    return sum(item["remaining"] for item in active), active


@dataclass(frozen=True, slots=True)
class OptimizationPlan:
    generated_at: int
    current_points: int | None
    monthly_spend: int
    monthly_penalty: int
    spend_cycle_start: int
    spend_cycle_end: int
    spend_cycle_source: str
    spend_cycle_day: int
    minimum_spend: int
    spend_shortfall: int
    package_remaining: int
    daily_unlocks: int
    catch_up_unlocks: int
    unlocks_now: int
    packages_to_buy: int
    affordable_packages: int
    monthly_remaining: int
    list_remaining: int
    monthly_daily_slots: int
    list_daily_slots: int
    purchase_reasons: tuple[str, ...]
    blocked_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_optimization_plan(
    *,
    history: list[dict[str, Any]],
    packages: list[dict[str, Any]],
    tasks: dict[str, dict[str, Any]],
    now: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
    minimum_spend: int = 450,
    package_price: int = 450,
    package_quota: int = 30,
    spend_trigger_day: int = 25,
    points_reserve: int = 0,
    max_auto_purchases: int = 2,
    max_auto_unlocks: int = 50,
    spend_cycle_days: int = 30,
) -> OptimizationPlan:
    """Build a safe just-in-time purchase and catch-up plan."""

    if now is None:
        now = datetime.now(ZoneInfo(timezone_name))
    elif now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo(timezone_name))

    cycle_start, cycle_end, cycle_source = resolve_spend_cycle(
        history,
        now=now,
        cycle_days=spend_cycle_days,
    )
    current_points, monthly_spend, monthly_penalty = summarize_monthly_spend(
        history,
        now=now,
        cycle_days=spend_cycle_days,
    )
    package_remaining, _ = summarize_packages(packages, now=now)

    daily_task = tasks.get("D_UL_1")
    monthly_task = tasks.get("M_UL_50")
    list_task = tasks.get("M_UL_ML_20")
    daily_pending = bool(daily_task and not daily_task.get("is_finish"))
    daily_unlocks = 1 if daily_pending else 0

    monthly_remaining = _task_remaining(monthly_task)
    list_remaining = _task_remaining(list_task)
    monthly_slots = _safe_daily_slots(
        monthly_task,
        now=now,
        daily_pending=daily_pending,
        fallback=30,
    )
    list_slots = _safe_daily_slots(
        list_task,
        now=now,
        daily_pending=daily_pending,
        fallback=30,
    )

    monthly_catch_up = max(0, monthly_remaining - monthly_slots)
    list_catch_up = max(0, list_remaining - list_slots)
    catch_up_unlocks = min(
        max(monthly_catch_up, list_catch_up),
        max(0, max_auto_unlocks - daily_unlocks),
    )
    unlocks_now = daily_unlocks + catch_up_unlocks

    spend_shortfall = max(0, minimum_spend - monthly_spend)
    quota_shortfall = max(0, unlocks_now - package_remaining)
    quota_packages = (
        math.ceil(quota_shortfall / package_quota)
        if quota_shortfall and package_quota > 0
        else 0
    )
    cycle_day = max(1, (now - cycle_start).days + 1)
    trigger_day = max(1, min(max(1, spend_cycle_days), spend_trigger_day))
    minimum_spend_package = int(
        spend_shortfall > 0 and cycle_day >= trigger_day
    )
    desired_packages = max(quota_packages, minimum_spend_package)

    if current_points is None or package_price <= 0:
        affordable_packages = 0
    else:
        affordable_packages = max(
            0, (current_points - max(0, points_reserve)) // package_price
        )
    packages_to_buy = min(
        desired_packages,
        affordable_packages,
        max(0, max_auto_purchases),
    )

    purchase_reasons: list[str] = []
    if quota_packages:
        purchase_reasons.append(f"当前计划缺少 {quota_shortfall} 次解锁额度")
    if minimum_spend_package:
        purchase_reasons.append(f"本月合格消费还差 {spend_shortfall} 分")

    blocked_reasons: list[str] = []
    if desired_packages and current_points is None:
        blocked_reasons.append("无法读取当前积分，已禁止自动购买")
    elif desired_packages > affordable_packages:
        needed = package_price + max(0, points_reserve)
        blocked_reasons.append(f"积分不足，单次购包至少需要余额 {needed} 分")
    if desired_packages > max_auto_purchases:
        blocked_reasons.append(
            f"本次最多自动购买 {max_auto_purchases} 个资源包"
        )
    if unlocks_now > package_remaining + packages_to_buy * package_quota:
        available = package_remaining + packages_to_buy * package_quota
        blocked_reasons.append(f"本次最多可执行 {available} 次解锁")

    return OptimizationPlan(
        generated_at=int(now.timestamp()),
        current_points=current_points,
        monthly_spend=monthly_spend,
        monthly_penalty=monthly_penalty,
        spend_cycle_start=int(cycle_start.timestamp()),
        spend_cycle_end=int(cycle_end.timestamp()),
        spend_cycle_source=cycle_source,
        spend_cycle_day=cycle_day,
        minimum_spend=minimum_spend,
        spend_shortfall=spend_shortfall,
        package_remaining=package_remaining,
        daily_unlocks=daily_unlocks,
        catch_up_unlocks=catch_up_unlocks,
        unlocks_now=unlocks_now,
        packages_to_buy=packages_to_buy,
        affordable_packages=affordable_packages,
        monthly_remaining=monthly_remaining,
        list_remaining=list_remaining,
        monthly_daily_slots=monthly_slots,
        list_daily_slots=list_slots,
        purchase_reasons=tuple(purchase_reasons),
        blocked_reasons=tuple(blocked_reasons),
    )
