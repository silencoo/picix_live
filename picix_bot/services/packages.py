"""Personal package state and usable-quota aggregation."""
from __future__ import annotations

from datetime import datetime

from picix_bot.api.client import _api_failure, api_request
from picix_bot.optimizer import summarize_packages


def get_package_info():
    """获取最早到期的可用资源包，兼容旧调用方。"""
    packages = get_package_list()
    _, active = summarize_packages(packages, now=datetime.now().astimezone())
    if active:
        return active[0]["raw"]
    return None


def get_package_state():
    """读取个人资源包，并保留“无数据”和“请求失败”的区别。"""
    result = api_request("GET", "/Packages/listMine")
    failure = _api_failure(result, "暂时无法读取资源包")
    if failure:
        return {**failure, "packages": []}

    packages = result.get("data")
    if not isinstance(packages, list):
        return {
            "available": False,
            "auth_failed": False,
            "retryable": False,
            "error": "资源包接口返回格式已变化",
            "packages": [],
        }
    return {
        "available": True,
        "auth_failed": False,
        "retryable": False,
        "error": "",
        "packages": packages,
    }


def get_package_list():
    """获取个人资源包列表"""
    state = get_package_state()
    return state["packages"] if state["available"] else []


def get_package_summary():
    """汇总所有未过期资源包，避免只读取第一包导致误购。"""
    state = get_package_state()
    packages = state["packages"]
    remaining, active = summarize_packages(
        packages,
        now=datetime.now().astimezone(),
    )
    return {
        "remaining": remaining,
        "active": active,
        "all": packages,
        "available": state["available"],
        "auth_failed": state["auth_failed"],
        "retryable": state["retryable"],
        "error": state["error"],
    }
