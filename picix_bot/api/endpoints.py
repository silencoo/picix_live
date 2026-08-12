"""Thin wrappers around read-only Picix API endpoints."""
from __future__ import annotations

from .client import _api_failure, _get_list_api_state, api_request


def get_movie_lists(page=1, sort="favorite_count"):
    """获取片单列表"""
    params = {"page": page, "sort": sort}
    result = api_request("GET", "/Movies/listMovieList", params=params)
    if result and result.get("success"):
        return result.get("data", [])
    return []


def get_movie_list_detail(list_id):
    """获取片单详情"""
    params = {"listId": list_id}
    result = api_request("GET", "/Movies/getMovieList", params=params)
    if result and result.get("success"):
        return result.get("data", {})
    return {}


def get_recommend_movies():
    """获取推荐电影列表"""
    result = api_request("GET", "/Movies/listRecommend")
    if result and result.get("success"):
        return result.get("data", [])
    return []


def search_movies(keyword, page=0):
    """搜索电影"""
    params = {"keyword": keyword, "page": page}
    result = api_request("GET", "/Movies/search", params=params)
    if result and result.get("success"):
        return result.get("data", [])
    return []


def get_movie_detail(movie_id):
    """获取电影详情（已解锁可返回播放链接）"""
    params = {"movieId": movie_id}
    result = api_request("GET", "/Movies/detail", params=params)
    if result and result.get("success"):
        return result.get("data", {})
    return {}


def get_point_history_state():
    return _get_list_api_state("/Users/listPointHistory", "积分记录")


def get_point_history():
    """获取积分历史记录；兼容旧调用方。"""
    state = get_point_history_state()
    return state["items"] if state["available"] else []


def get_paid_movies_state(page=1):
    """读取一页已购影片，保留故障与真实空页的区别。"""
    params = {"page": page, "type": "movies"}
    result = api_request("GET", "/Users/listPaidResouces", params=params)
    failure = _api_failure(result, "暂时无法读取已购影片")
    if failure:
        return {**failure, "items": []}
    items = result.get("data")
    if not isinstance(items, list):
        return {
            "available": False,
            "auth_failed": False,
            "retryable": False,
            "error": "已购影片接口返回格式已变化",
            "items": [],
        }
    return {
        "available": True,
        "auth_failed": False,
        "retryable": False,
        "error": "",
        "items": items,
    }


def get_paid_movies(page=1):
    """获取一页已购买影片；兼容旧调用方。"""
    state = get_paid_movies_state(page)
    return state["items"] if state["available"] else []


def get_all_paid_movies_state():
    """读取所有已购影片 ID，任何分页故障都使整个快照不可用。"""
    paid_movie_ids = set()
    page = 1
    max_pages = 10  # 最多检查10页，避免无限循环

    while page <= max_pages:
        state = get_paid_movies_state(page=page)
        if not state["available"]:
            return {**state, "items": set()}
        movies = state["items"]
        if not movies:  # 没有更多电影了
            break

        for movie in movies:
            movie_id = movie.get("id")
            if movie_id:
                paid_movie_ids.add(movie_id)

        # 如果返回的电影数量少于预期，可能已经到最后一页了
        if len(movies) < 20:  # 假设每页20个（可以根据实际情况调整）
            break

        page += 1

    return {
        "available": True,
        "auth_failed": False,
        "retryable": False,
        "error": "",
        "items": paid_movie_ids,
    }


def get_all_paid_movies():
    """获取所有已购影片 ID；兼容旧调用方。"""
    state = get_all_paid_movies_state()
    return state["items"] if state["available"] else set()
