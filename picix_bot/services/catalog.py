"""Store catalog normalization and guarded purchase operations."""
from __future__ import annotations

import json
import re

from picix_bot.api.client import _api_failure, api_request


def _first_value(data, keys, default=None):
    """从字典中取第一个非空值"""
    for key in keys:
        if key in data:
            value = data.get(key)
            if value is None:
                continue
            if isinstance(value, str) and value.strip() == "":
                continue
            return value
    return default


def _extract_package_items(data):
    """从接口 data 中抽取资源包列表"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # 处理分类列表（如 package / inviteCode / redeemCode）
        grouped_items = []
        for key, value in data.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        item = dict(item)
                        item.setdefault("_category", key)
                    grouped_items.append(item)
        if grouped_items:
            return grouped_items
        for key in ("list", "items", "rows", "data", "goods", "packages"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        # 如果 data 本身就是一个资源包对象
        if any(k in data for k in ("goodId", "goodsId", "id", "name", "title")):
            return [data]
    return []


def _infer_package_quota(package):
    """读取商品次数；当前线上接口仅在 desc 中返回“30次包”。"""
    explicit = _first_value(
        package,
        ["total", "count", "times", "quantity", "num", "quota"],
    )
    if explicit is not None:
        return explicit

    candidates = []
    for key in ("desc", "description", "remark", "note", "name", "title"):
        text = str(package.get(key) or "")
        for pattern in (r"(\d+)\s*次包", r"可解锁\s*(\d+)\s*个"):
            candidates.extend(int(value) for value in re.findall(pattern, text))
    if candidates and len(set(candidates)) == 1:
        return candidates[0]
    return None


def get_purchasable_package_state():
    """读取商城商品，并保留认证、临时故障和真实空列表状态。"""
    endpoints = [
        ("/Malls/listGoods", None),
        ("/Malls/listGoods", {"type": "package"}),
        ("/Malls/listGoods", {"type": "packages"}),
        ("/Packages/list", None),
        ("/Packages/listAll", None),
    ]
    failures = []
    for endpoint, params in endpoints:
        result = api_request("GET", endpoint, params=params)
        failure = _api_failure(result, "暂时无法读取商城商品")
        if failure:
            failures.append(failure)
            if failure["auth_failed"]:
                break
            continue

        data = result.get("data")
        items = _extract_package_items(data)
        known_keys = {
            "package", "inviteCode", "redeemCode", "list", "items",
            "rows", "data", "goods", "packages",
        }
        recognized_empty = (
            data == []
            or (isinstance(data, dict) and (not data or bool(known_keys & data.keys())))
        )
        if items or recognized_empty:
            return {
                "available": True,
                "auth_failed": False,
                "retryable": False,
                "error": "",
                "items": items,
                "endpoint": endpoint,
                "params": params,
            }
        failures.append(
            {
                "available": False,
                "auth_failed": False,
                "retryable": False,
                "error": "商城接口返回格式已变化",
            }
        )

    failure = next(
        (item for item in failures if item.get("auth_failed")),
        failures[0] if failures else _api_failure(None),
    )
    return {
        **failure,
        "items": [],
        "endpoint": None,
        "params": None,
    }


def get_purchasable_packages():
    """获取可购买资源包列表"""
    state = get_purchasable_package_state()
    return state["items"], state["endpoint"], state["params"]


def show_purchasable_packages():
    """显示可购买资源包"""
    print("=" * 60)
    print("可购买资源包")
    print("=" * 60)

    packages, endpoint, params = get_purchasable_packages()

    if endpoint:
        if params:
            print(f"接口: {endpoint} | 参数: {json.dumps(params, ensure_ascii=False)}")
        else:
            print(f"接口: {endpoint}")

    if not packages:
        print("未找到可购买资源包（接口可能已变化或账号权限不足）")
        return

    for idx, pkg in enumerate(packages, 1):
        name = _first_value(pkg, ["name", "title", "goodsName", "goodName", "packageName"])
        desc = _first_value(pkg, ["desc", "description", "remark", "note"])
        good_id = _first_value(pkg, ["goodId", "goodsId", "id"])
        price = _first_value(pkg, ["price", "point", "points", "amount", "cost", "coin"])
        total = _infer_package_quota(pkg)
        status = _first_value(pkg, ["status", "state", "isEnable", "enabled"])

        header = f"{idx}. {name}" if name else f"{idx}. 资源包"
        if good_id is not None:
            header += f" (ID: {good_id})"
        print(f"\n{header}")

        if desc:
            print(f"  说明: {desc}")
        if price is not None:
            print(f"  价格/积分: {price}")
        if total is not None:
            print(f"  次数: {total}")
        if status is not None:
            print(f"  状态: {status}")


def find_purchasable_package(good_id, state=None):
    """查找指定商品，并返回可用于购买前校验的标准字段。"""
    state = state or get_purchasable_package_state()
    packages = state["items"] if state["available"] else []
    endpoint = state.get("endpoint")
    params = state.get("params")
    expected_id = str(good_id)
    for package in packages:
        actual_id = _first_value(package, ["goodId", "goodsId", "id"])
        if actual_id is None or str(actual_id) != expected_id:
            continue
        return {
            "good_id": str(actual_id),
            "price": _first_value(
                package, ["price", "point", "points", "amount", "cost", "coin"]
            ),
            "quota": _infer_package_quota(package),
            "name": _first_value(
                package,
                ["name", "title", "goodsName", "goodName", "packageName"],
            ),
            "endpoint": endpoint,
            "params": params,
            "raw": package,
        }
    return None


def validate_purchasable_package(good_id, expected_price, expected_quota):
    """购买前核对商品 ID、价格和次数，防止接口变化造成误扣。"""
    state = get_purchasable_package_state()
    if not state["available"]:
        return False, f"{state['error']}，已禁止自动购买", None

    package = find_purchasable_package(good_id, state=state)
    if not package:
        return False, "商城中未找到配置的轻量包，已禁止自动购买", None

    price = package.get("price")
    quota = package.get("quota")
    if price is None or quota is None:
        return (
            False,
            "商城未返回可校验的价格或次数，已禁止自动购买",
            package,
        )
    try:
        if int(price) != int(expected_price):
            return (
                False,
                f"轻量包价格已变化（接口 {price}，配置 {expected_price}）",
                package,
            )
        if int(quota) != int(expected_quota):
            return (
                False,
                f"轻量包次数已变化（接口 {quota}，配置 {expected_quota}）",
                package,
            )
    except (TypeError, ValueError):
        return False, "商城返回的价格或次数无法识别", package
    return True, "", package


def buy_lightweight_package(good_id="1"):
    """购买轻量包。调用前应先执行商品参数校验。"""
    print("正在购买轻量包...")
    data = {"goodId": str(good_id)}
    result = api_request("POST", "/Malls/payGood", data=data)
    if result:
        if result.get("success"):
            print(f"✓ 购买成功: {result.get('msg', '无消息')}")
            return True, result.get("msg")
        else:
            error_msg = result.get('msg', '未知错误')
            print(f"✗ 购买失败: {error_msg}")
            return False, error_msg
    return False, "请求失败"
