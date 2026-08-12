"""Movie selection, unlock execution, and local unlock records."""
from __future__ import annotations

from datetime import datetime
import json
import time

from picix_bot.api.client import DATA_DIR, api_request, load_json_file, save_json_file
from picix_bot.api.endpoints import (
    get_all_paid_movies_state,
    get_movie_list_detail,
    get_movie_lists,
    get_recommend_movies,
)
from picix_bot.services.packages import get_package_summary
from picix_bot.services.tasks import analyze_tasks

UNLOCK_LOG_FILE = DATA_DIR / "unlock_log.json"


def unlock_movie(movie_id, list_id=None):
    """解锁电影
    Args:
        movie_id: 电影ID
        list_id: 片单ID，如果从片单解锁则传递片单ID，如果从推荐列表解锁则传递None或0
    """
    # 确保 movieId 是整数类型
    try:
        movie_id = int(movie_id) if movie_id else None
    except (ValueError, TypeError):
        print(f"错误: 无法将 movie_id 转换为整数: {movie_id}")
        return False

    if not movie_id:
        print(f"错误: 无效的 movie_id: {movie_id}")
        return False

    # 构建请求数据
    data = {
        "movieId": movie_id
    }

    # 如果提供了片单ID，则添加到请求中
    # 根据 curl 示例，fromMovieList 应该是字符串格式的片单ID
    if list_id:
        try:
            list_id_int = int(list_id) if list_id else None
            if list_id_int:
                data["fromMovieList"] = str(list_id_int)  # 使用字符串格式（与 curl 示例一致）
        except (ValueError, TypeError):
            print(f"警告: 无法将 list_id 转换为整数: {list_id}，将不传递 fromMovieList 参数")

    # 调试信息：打印实际发送的 payload
    print(f"调试: 解锁请求 payload: {json.dumps(data, ensure_ascii=False)}")
    if list_id:
        print(f"调试: 从片单解锁，片单ID: {list_id}")
    else:
        print("调试: 从推荐列表解锁")

    result = api_request("POST", "/Movies/unlock", data=data)
    if result:
        if result.get("success"):
            print(f"调试: 解锁成功，响应: {result.get('msg', '无消息')}")
            return (True, None)
        else:
            error_msg = result.get('msg', '未知错误')
            error_detail = json.dumps(result, ensure_ascii=False, indent=2)
            print(f"调试: 解锁失败，API返回: {error_msg}")
            print(f"调试: 完整响应: {error_detail}")
            return (False, f"API错误: {error_msg}\n\n完整响应:\n{error_detail}")
    else:
        error_msg = "API请求返回 None（可能是网络错误或服务器错误）"
        print(f"调试: 解锁失败，{error_msg}")
        return (False, error_msg)


def get_unlock_log():
    """获取解锁记录"""
    return load_json_file(UNLOCK_LOG_FILE, {
        "unlocked_movies": [],
        "daily_unlocks": {},
        "monthly_stats": {}
    })


def save_unlock_record(movie_id, from_list, list_id=None):
    """保存解锁记录"""
    log = get_unlock_log()
    today = datetime.now().strftime("%Y-%m-%d")
    current_month = datetime.now().strftime("%Y-%m")

    # 记录已解锁的电影
    if movie_id not in log["unlocked_movies"]:
        log["unlocked_movies"].append(movie_id)

    # 记录每日解锁
    if today not in log["daily_unlocks"]:
        log["daily_unlocks"][today] = []
    log["daily_unlocks"][today].append({
        "movie_id": movie_id,
        "from_list": from_list,
        "list_id": list_id,
        "timestamp": int(time.time())
    })

    # 记录月度统计
    if current_month not in log["monthly_stats"]:
        log["monthly_stats"][current_month] = {
            "total": 0,
            "from_list": 0,
            "list_ids": set()
        }

    stats = log["monthly_stats"][current_month]
    stats["total"] += 1
    if from_list:
        stats["from_list"] += 1
        if list_id:
            if isinstance(stats["list_ids"], list):
                stats["list_ids"] = set(stats["list_ids"])
            stats["list_ids"].add(list_id)

    # 转换set为list以便JSON序列化
    if isinstance(stats["list_ids"], set):
        stats["list_ids"] = list(stats["list_ids"])

    save_json_file(UNLOCK_LOG_FILE, log)
    return log


def find_unlocked_movie_from_list(list_id, unlocked_movies, paid_movies=None):
    """从片单中找到一个未解锁的电影
    Args:
        list_id: 片单ID
        unlocked_movies: 本地记录的已解锁电影集合
        paid_movies: 服务器端的已购买电影集合（可选，如果为None则自动获取）
    """
    if paid_movies is None:
        paid_state = get_all_paid_movies_state()
        if not paid_state["available"]:
            return None
        paid_movies = paid_state["items"]

    detail = get_movie_list_detail(list_id)
    if not detail:
        return None

    movie_list = detail.get("list", [])
    for movie in movie_list:
        movie_id = movie.get("id")
        # 同时检查本地记录和服务器端的已解锁列表
        if movie_id and movie_id not in unlocked_movies and movie_id not in paid_movies:
            return movie_id
    return None


def find_unlocked_movie_from_recommend(unlocked_movies, paid_movies=None):
    """从推荐列表中找到未解锁的电影
    Args:
        unlocked_movies: 本地记录的已解锁电影集合
        paid_movies: 服务器端的已购买电影集合（可选，如果为None则自动获取）
    """
    if paid_movies is None:
        paid_state = get_all_paid_movies_state()
        if not paid_state["available"]:
            return None
        paid_movies = paid_state["items"]

    recommend = get_recommend_movies()
    for movie in recommend:
        movie_id = movie.get("id")
        # 同时检查本地记录和服务器端的已解锁列表
        if movie_id and movie_id not in unlocked_movies and movie_id not in paid_movies:
            return movie_id
    return None


def pick_next_movie(all_unlocked_movies, paid_movies, prefer_list=True):
    """选择一个未解锁影片；片单任务未完成时优先从片单选择。"""
    if prefer_list:
        page = 1
        while page <= 10:
            movie_lists = get_movie_lists(page=page, sort="favorite_count")
            if not movie_lists:
                break
            for movie_list in movie_lists:
                list_id = movie_list.get("id")
                movie_id = find_unlocked_movie_from_list(
                    list_id,
                    all_unlocked_movies,
                    paid_movies,
                )
                if movie_id:
                    return movie_id, True, list_id
            page += 1

    movie_id = find_unlocked_movie_from_recommend(
        all_unlocked_movies,
        paid_movies,
    )
    if movie_id:
        return movie_id, False, None
    return None, False, None


def unlock_movies_batch(count, *, prefer_list=True):
    """批量解锁并返回结构化结果，供手动命令和自动优化共用。"""
    requested = max(0, int(count))
    summary = get_package_summary()
    if not summary["available"]:
        return {
            "requested": requested,
            "attempted": 0,
            "successes": [],
            "failure": f"{summary['error']}；无法确认额度，已停止解锁",
            "available_before": None,
        }
    available = summary["remaining"]
    target = min(requested, available)
    result = {
        "requested": requested,
        "attempted": target,
        "successes": [],
        "failure": None,
        "available_before": available,
    }
    if target <= 0:
        result["failure"] = "没有可用的资源包次数"
        return result

    tasks = analyze_tasks() or {}
    list_task = tasks.get("M_UL_ML_20") or {}
    list_remaining = max(
        0,
        int(list_task.get("target") or 0) - int(list_task.get("current") or 0),
    )
    if list_task.get("is_finish"):
        list_remaining = 0

    log = get_unlock_log()
    unlocked_movies = set(log["unlocked_movies"])
    paid_state = get_all_paid_movies_state()
    if not paid_state["available"]:
        result["attempted"] = 0
        result["failure"] = (
            f"{paid_state['error']}；无法排除重复解锁，已停止执行"
        )
        return result
    paid_movies = paid_state["items"]
    all_unlocked_movies = unlocked_movies | paid_movies

    for _ in range(target):
        use_list = prefer_list and list_remaining > 0
        movie_id, from_list, list_id = pick_next_movie(
            all_unlocked_movies,
            paid_movies,
            use_list,
        )
        if not movie_id:
            result["failure"] = "未找到可解锁的电影"
            break

        success, error_msg = unlock_movie(
            movie_id,
            list_id=list_id if from_list else None,
        )
        if not success:
            result["failure"] = error_msg or "未知错误"
            break

        save_unlock_record(movie_id, from_list, list_id)
        all_unlocked_movies.add(movie_id)
        paid_movies.add(movie_id)
        if from_list:
            list_remaining = max(0, list_remaining - 1)
        result["successes"].append(
            {
                "movie_id": movie_id,
                "from_list": from_list,
                "list_id": list_id,
            }
        )
        time.sleep(0.8)

    return result
