"""High-level safe automation workflows for planning, buying, and unlocking."""
from __future__ import annotations

from datetime import datetime
import time

from picix_bot.api.endpoints import get_all_paid_movies_state, get_point_history_state
from picix_bot.optimizer import build_optimization_plan
from picix_bot.services.catalog import (
    buy_lightweight_package,
    validate_purchasable_package,
)
from picix_bot.services.packages import get_package_state, get_package_summary
from picix_bot.services.tasks import (
    accept_default_tasks,
    analyze_tasks,
    get_task_state,
    should_unlock_from_list,
)
from picix_bot.services.unlock import (
    find_unlocked_movie_from_list,
    find_unlocked_movie_from_recommend,
    get_unlock_log,
    save_unlock_record,
    unlock_movie,
    unlock_movies_batch,
)
from picix_bot.api.endpoints import get_movie_lists


def ensure_package_and_unlock():
    """确保有资源包可用并执行解锁"""
    print("=" * 60)
    print(f"自动购买并解锁 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 检查资源包状态
    summary = get_package_summary()
    if not summary["available"]:
        print(f"❌ {summary['error']}。状态不确定，禁止自动购买")
        return False

    remaining = summary["remaining"]
    need_buy = remaining <= 0
    print(f"当前全部有效资源包剩余: {remaining}")
    if need_buy:
        print("⚠️ 已确认资源包次数为 0，需要购买")
    else:
        print("✓ 资源包充足，无需购买")

    # 2. 如果需要，执行购买
    if need_buy:
        valid, reason, _ = validate_purchasable_package("1", 450, 30)
        if not valid:
            print(f"❌ {reason}")
            return False
        success, msg = buy_lightweight_package()
        if not success:
            print(f"❌ 无法购买资源包，终止流程: {msg}")
            return False

        # 购买成功后，稍作等待并重新检查（可选）
        time.sleep(2)
        summary = get_package_summary()
        if not summary["available"] or summary["remaining"] <= 0:
            print("❌ 购买后未能确认额度到账，终止解锁")
            return False
        print(f"购买后状态: 剩余 {summary['remaining']}")

    # 3. 执行每日解锁
    return daily_unlock()


def build_live_optimization_plan(**options):
    """读取实时状态并生成积分优化计划。"""
    task_state = get_task_state()
    history_state = get_point_history_state()
    package_state = get_package_state()
    failures = [
        f"{label}状态不可用：{state['error']}"
        for label, state in (
            ("任务", task_state),
            ("积分", history_state),
            ("资源包", package_state),
        )
        if not state["available"]
    ]
    if failures:
        raise RuntimeError("；".join(failures))

    tasks = analyze_tasks(task_state["items"])
    if not tasks or not history_state["items"]:
        raise RuntimeError("任务或积分记录为空，无法生成可靠计划")
    return build_optimization_plan(
        history=history_state["items"],
        packages=package_state["packages"],
        tasks=tasks,
        **options,
    )


def execute_points_optimization(
    *,
    allow_purchase=True,
    timezone_name="Asia/Shanghai",
    minimum_spend=450,
    package_good_id="1",
    package_price=450,
    package_quota=30,
    spend_trigger_day=25,
    points_reserve=0,
    max_auto_purchases=2,
    max_auto_unlocks=50,
    spend_cycle_days=30,
):
    """执行一次按余额、低消和任务期限生成的积分最大化计划。"""
    options = {
        "timezone_name": timezone_name,
        "minimum_spend": minimum_spend,
        "package_price": package_price,
        "package_quota": package_quota,
        "spend_trigger_day": spend_trigger_day,
        "points_reserve": points_reserve,
        "max_auto_purchases": max_auto_purchases,
        "max_auto_unlocks": max_auto_unlocks,
        "spend_cycle_days": spend_cycle_days,
    }
    report = {
        "success": False,
        "plan": None,
        "purchases": [],
        "unlock_result": None,
        "messages": [],
    }

    # 所有会影响购买决策的数据必须明确可用。空列表可能是真空，也可能是
    # 401/522/超时；在确认状态前不领取任务、更不允许购买。
    task_state = get_task_state()
    history_state = get_point_history_state()
    package_state = get_package_state()
    unavailable = [
        ("任务", task_state),
        ("积分", history_state),
        ("资源包", package_state),
    ]
    for label, state in unavailable:
        if not state["available"]:
            report["messages"].append(f"{label}状态不可用：{state['error']}")
    if report["messages"]:
        report["messages"].append("状态不确定，本次不会购买或解锁")
        return report

    accept_results = accept_default_tasks()
    failed_accepts = [
        unique
        for unique, info in accept_results.items()
        if info.get("status") == "failed"
    ]
    if failed_accepts:
        report["messages"].append(
            f"以下任务领取失败：{', '.join(failed_accepts)}"
        )

    # 领取任务后重新读取，避免使用领取前的进度；再次失败仍应 fail closed。
    task_state = get_task_state()
    if not task_state["available"]:
        report["messages"].append(f"任务状态不可用：{task_state['error']}")
        report["messages"].append("状态不确定，本次不会购买或解锁")
        return report
    tasks = analyze_tasks(task_state["items"])
    history = history_state["items"]
    packages = package_state["packages"]
    if not tasks or not history:
        report["messages"].append("任务或积分记录为空，无法安全生成购买计划")
        return report

    plan = build_optimization_plan(
        history=history,
        packages=packages,
        tasks=tasks,
        **options,
    )
    report["plan"] = plan.to_dict()
    report["messages"].extend(plan.blocked_reasons)

    if plan.packages_to_buy and not allow_purchase:
        report["messages"].append(
            f"计划需要购买 {plan.packages_to_buy} 个轻量包，但自动购买已关闭"
        )
    elif plan.packages_to_buy:
        valid, reason, package = validate_purchasable_package(
            package_good_id,
            package_price,
            package_quota,
        )
        if not valid:
            report["messages"].append(reason)
            return report

        package_name = package.get("name") or f"商品 {package_good_id}"
        for _ in range(plan.packages_to_buy):
            success, message = buy_lightweight_package(package_good_id)
            report["purchases"].append(
                {
                    "success": success,
                    "message": message,
                    "good_id": str(package_good_id),
                    "name": package_name,
                    "price": package_price,
                }
            )
            if not success:
                report["messages"].append(f"购买失败：{message}")
                break
            time.sleep(1)

    # 必须从资源包接口确认额度已到账，避免无包时退化为20分直购影片。
    verified_summary = get_package_summary()
    if not verified_summary["available"]:
        report["messages"].append(
            f"无法确认购买后额度：{verified_summary['error']}，已停止解锁"
        )
        return report
    verified_quota = verified_summary["remaining"]
    unlock_count = min(plan.unlocks_now, verified_quota)
    if plan.unlocks_now > unlock_count:
        report["messages"].append(
            f"计划解锁 {plan.unlocks_now} 部，但已确认额度仅 {verified_quota} 次"
        )

    if unlock_count:
        report["unlock_result"] = unlock_movies_batch(
            unlock_count,
            prefer_list=plan.list_remaining > 0,
        )

    successful_purchases = sum(
        1 for purchase in report["purchases"] if purchase["success"]
    )
    successful_unlocks = len(
        (report["unlock_result"] or {}).get("successes", [])
    )
    report["success"] = (
        not report["messages"]
        or successful_purchases > 0
        or successful_unlocks > 0
        or (plan.unlocks_now == 0 and plan.packages_to_buy == 0)
    )
    return report


def daily_unlock():
    """执行每日解锁任务"""
    print("=" * 60)
    print(f"每日解锁任务 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    task_state = get_task_state()
    package_summary = get_package_summary()
    if not task_state["available"]:
        print(f"❌ {task_state['error']}，已停止解锁")
        return False
    if not package_summary["available"]:
        print(f"❌ {package_summary['error']}，无法确认额度，已停止解锁")
        return False
    if package_summary["remaining"] <= 0:
        print("❌ 已确认资源包次数为 0，已停止解锁")
        return False

    # 领取常用任务（避免未领取导致进度异常）
    accept_results = accept_default_tasks()
    for unique, info in accept_results.items():
        if info["status"] == "skipped":
            print(f"✓ 任务已存在 {unique}: {info['msg']}")
        elif info["success"]:
            print(f"✓ 已领取任务 {unique}: {info['msg']}")
        else:
            if info["msg"]:
                print(f"⚠️ 任务 {unique} 领取失败: {info['msg']}")

    # 分析任务状态
    refreshed_task_state = get_task_state()
    if not refreshed_task_state["available"]:
        print(f"❌ {refreshed_task_state['error']}，已停止解锁")
        return False
    tasks = analyze_tasks(refreshed_task_state["items"])
    if not tasks:
        print("无法获取任务状态，退出")
        return False

    # 显示任务进度
    print("\n当前任务进度:")
    for unique, info in tasks.items():
        status = "✓ 已完成" if info["is_finish"] else "进行中"
        print(f"  {info['name']}: {info['current']}/{info['target']} ({status}) - {info['point']}分")

    # 检查每日任务是否已完成
    daily_task = tasks.get("D_UL_1")
    if daily_task and daily_task["is_finish"]:
        print("\n✓ 今日每日任务已完成，无需解锁")
        return True

    # 获取解锁记录
    log = get_unlock_log()
    unlocked_movies = set(log["unlocked_movies"])

    # 获取服务器端的已解锁电影列表（避免重复解锁）
    print("\n正在获取服务器端的已解锁电影列表...")
    paid_state = get_all_paid_movies_state()
    if not paid_state["available"]:
        print(f"❌ {paid_state['error']}，无法排除重复解锁，已停止执行")
        return False
    paid_movies = paid_state["items"]
    print(f"  服务器端已解锁电影数: {len(paid_movies)}")

    # 合并本地和服务器端的已解锁列表
    all_unlocked_movies = unlocked_movies | paid_movies
    print(f"  总计已解锁电影数: {len(all_unlocked_movies)} (本地: {len(unlocked_movies)}, 服务器: {len(paid_movies)})")

    # 获取月度统计
    current_month = datetime.now().strftime("%Y-%m")
    monthly_stats = log["monthly_stats"].get(current_month, {
        "total": 0,
        "from_list": 0,
        "list_ids": []
    })

    # 每日解锁策略：片单任务完成后不再从片单获取
    movie_id = None
    from_list = False
    list_id = None
    use_list = should_unlock_from_list(tasks)

    if use_list:
        # 遍历所有片单，直到找到未解锁的电影
        page = 1
        max_pages = 10  # 最多检查10页，避免无限循环
        print(f"\n正在从片单中查找未解锁的电影... (当前片单解锁: {monthly_stats['from_list']}/20)")

        while not movie_id and page <= max_pages:
            movie_lists = get_movie_lists(page=page, sort="favorite_count")
            if not movie_lists:  # 没有更多片单了
                break

            for ml in movie_lists:
                list_id = ml.get("id")
                movie_id = find_unlocked_movie_from_list(list_id, all_unlocked_movies, paid_movies)
                if movie_id:
                    from_list = True
                    print(f"  找到片单: {ml.get('title')} (ID: {list_id})")
                    break

            if movie_id:
                break
            page += 1
    else:
        print("\n片单任务已完成，跳过片单解锁，改从推荐列表获取...")

    # 如果没找到，从推荐列表选择
    if not movie_id:
        print("\n从推荐列表中查找未解锁的电影...")
        movie_id = find_unlocked_movie_from_recommend(all_unlocked_movies, paid_movies)
        if movie_id:
            print(f"  找到推荐电影: {movie_id}")

    if not movie_id:
        print("\n✗ 未找到可解锁的电影")
        return False

    # 执行解锁
    if from_list and list_id:
        print(f"\n正在解锁电影 ID: {movie_id} (来自片单: {list_id})")
        success, error_msg = unlock_movie(movie_id, list_id=list_id)
    else:
        print(f"\n正在解锁电影 ID: {movie_id} (来自推荐列表)")
        success, error_msg = unlock_movie(movie_id, list_id=None)

    if success:
        print("✓ 解锁成功！")
        save_unlock_record(movie_id, from_list, list_id)

        # 更新任务状态
        time.sleep(1)  # 等待服务器更新
        tasks = analyze_tasks()
        if tasks:
            print("\n更新后的任务进度:")
            for unique, info in tasks.items():
                status = "✓ 已完成" if info["is_finish"] else "进行中"
                print(f"  {info['name']}: {info['current']}/{info['target']} ({status})")

        return True
    else:
        print("✗ 解锁失败")
        if error_msg:
            print(f"错误详情: {error_msg}")
        return False
